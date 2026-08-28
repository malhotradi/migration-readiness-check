import googleapiclient.discovery
import google.auth
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

def check_gcp_target_readiness(
    project_id: str,
    instance_id: str,
    source_version_str: Optional[str] = None,
    auto_remediate: bool = False
) -> Dict[str, Any]:
    """
    Checks the target GCP Cloud SQL instance configurations to ensure compatibility
    with the source database and readiness for migration.
    """
    report = {
        "status": "PASS",
        "checks": [],
        "errors": []
    }

    try:
        # Obtain default credentials
        credentials, default_project = google.auth.default()
        if not project_id:
            project_id = default_project
            
        if not project_id:
            raise ValueError("GCP Project ID must be specified or default credentials must have a project.")
            
        sql_service = googleapiclient.discovery.build('sqladmin', 'v1beta4', credentials=credentials)
    except Exception as e:
        report["status"] = "WARNING"
        report["errors"].append(f"GCP Authentication failed: {str(e)}")
        report["checks"].append({
            "category": "GCP Authentication",
            "name": "GCP API Credentials Check",
            "status": "WARNING",
            "message": "Unable to initialize Google Cloud SDK clients.",
            "details": str(e),
            "remediation": "Ensure you are authenticated with GCP via `gcloud auth application-default login` or by setting `GOOGLE_APPLICATION_CREDENTIALS`."
        })
        return report

    # Helper for adding checks
    def add_check(category: str, name: str, status: str, message: str, details: Any, remediation: str = ""):
        report["checks"].append({
            "category": category,
            "name": name,
            "status": status,
            "message": message,
            "details": details,
            "remediation": remediation
        })
        if status == "FAIL":
            report["status"] = "FAIL"
        elif status == "WARNING" and report["status"] != "FAIL":
            report["status"] = "WARNING"

    # Fetch Cloud SQL instance details
    try:
        request = sql_service.instances().get(project=project_id, instance=instance_id)
        instance = request.execute()
    except Exception as e:
        add_check(
            category="Target Configuration",
            name="Cloud SQL Target Instance Discovery",
            status="FAIL",
            message=f"Could not find Cloud SQL instance '{instance_id}' in project '{project_id}'.",
            details=str(e),
            remediation="Verify that the project ID and instance ID are correct, and the SQL Admin API is enabled."
        )
        return report

    # 1. Check Cloud SQL State
    state = instance.get("state", "UNKNOWN")
    add_check(
        category="Target Configuration",
        name="Target Instance State",
        status="PASS" if state == "RUNNABLE" else "FAIL",
        message=f"Cloud SQL instance state is '{state}'.",
        details={"state": state},
        remediation="Make sure the target database instance is started and running before triggering the migration."
    )

    # 2. Check Cloud SQL Version Compatibility
    target_version_str = instance.get("databaseVersion", "")
    add_check(
        category="Target Configuration",
        name="Target Database Version",
        status="INFO",
        message=f"Target database version is {target_version_str}.",
        details={"database_version": target_version_str}
    )

    if source_version_str and target_version_str:
        # Compare versions (e.g. MYSQL_8_0 vs MYSQL_5_7)
        def parse_version(v_str):
            v_str = v_str.upper()
            if "8_0" in v_str or "8.0" in v_str:
                return 8.0
            if "5_7" in v_str or "5.7" in v_str:
                return 5.7
            if "5_6" in v_str or "5.6" in v_str:
                return 5.6
            return 0.0
            
        src_ver = parse_version(source_version_str)
        tgt_ver = parse_version(target_version_str)
        
        if src_ver > 0 and tgt_ver > 0:
            version_ok = tgt_ver >= src_ver
            add_check(
                category="Target Configuration",
                name="Version Compatibility Check",
                status="PASS" if version_ok else "FAIL",
                message=f"Source version is {source_version_str} and target version is {target_version_str}.",
                details={"source_version": source_version_str, "target_version": target_version_str},
                remediation=f"Target version {target_version_str} is lower than source version {source_version_str}. Target version must be >= source version."
            )

    # 3. Check Disk Settings (Capacity & Auto-Resize)
    settings = instance.get("settings", {})
    storage_limit_gb = int(settings.get("dataDiskSizeGb", 0))
    auto_resize = settings.get("storageAutoResize", False)
    disk_type = settings.get("dataDiskType", "PD_SSD")

    add_check(
        category="Target Capacity",
        name="Target Storage Capacity Check",
        status="PASS" if storage_limit_gb > 0 else "WARNING",
        message=f"Target disk size is {storage_limit_gb} GB ({disk_type}).",
        details={"disk_size_gb": storage_limit_gb, "disk_type": disk_type}
    )

    add_check(
        category="Target Capacity",
        name="Storage Auto-Resize Check",
        status="PASS" if auto_resize else "WARNING",
        message=f"Storage Auto-Resize is {'enabled' if auto_resize else 'disabled'}.",
        details={"storage_auto_resize": auto_resize},
        remediation="Enable Storage Auto-Resize on the target Cloud SQL instance to prevent out-of-disk failures during bulk loads."
    )

    # 4. Check Network Settings (Private IP vs Public IP / Authorized Networks)
    ip_configuration = settings.get("ipConfiguration", {})
    ipv4_enabled = ip_configuration.get("ipv4Enabled", False)
    private_network = ip_configuration.get("privateNetwork", "")
    authorized_networks = ip_configuration.get("authorizedNetworks", [])

    network_type = "Private IP" if private_network else "Public IP"
    add_check(
        category="Target Connectivity",
        name="Target Network Configuration Type",
        status="INFO",
        message=f"Target instance is configured with {network_type}.",
        details={
            "private_network": private_network,
            "ipv4_enabled": ipv4_enabled,
            "authorized_networks_count": len(authorized_networks)
        }
    )

    # 5. Check Target Database Flags
    database_flags = settings.get("databaseFlags", [])
    flags_dict = {flag.get("name"): flag.get("value") for flag in database_flags}
    
    # Check lower_case_table_names flag if specified
    add_check(
        category="Target Configuration",
        name="Target Database Flags Check",
        status="INFO",
        message=f"Instance has {len(database_flags)} database flags configured.",
        details={"flags": flags_dict}
    )

    return report
