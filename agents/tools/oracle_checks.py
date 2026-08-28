import oracledb
import re
from typing import Dict, List, Any, Optional

def detect_provider(host: str, user_provider: Optional[str] = None) -> str:
    """Detects the cloud provider based on the database hostname or user choice."""
    if user_provider:
        p = user_provider.upper()
        if "AWS" in p or "AMAZON" in p:
            return "AWS"
        if "AZURE" in p:
            return "AZURE"
        if "GCP" in p or "GOOGLE" in p:
            return "GCP"
        return "ON_PREMISE"
    
    host_lower = host.lower()
    if "rds.amazonaws.com" in host_lower:
        return "AWS"
    if "database.windows.net" in host_lower:
        return "AZURE"
    return "ON_PREMISE"

def check_oracle_readiness(
    host: str,
    user: str,
    password: str,
    database: str,  # This should be the SID or Service Name
    port: int = 1521,
    cloud_provider: Optional[str] = None,
    migration_type: str = "Online CDC",
    auto_remediate: bool = False
) -> Dict[str, Any]:
    """
    Performs a comprehensive set of pre-migration checks on the source Oracle database.
    Returns a structured report containing check details, status, and recommendations.
    """
    provider = detect_provider(host, cloud_provider)
    
    report = {
        "provider": provider,
        "connection_status": "FAILED",
        "overall_status": "PASS",
        "checks": [],
        "errors": []
    }
    
    # Establish connection using python-oracledb in thin mode
    try:
        # Construct DSN: host:port/service_name or host:port:SID
        # We default to service name syntax
        dsn = f"{host}:{port}/{database}"
        conn = oracledb.connect(
            user=user,
            password=password,
            dsn=dsn
        )
        cursor = conn.cursor()
        report["connection_status"] = "SUCCESS"
    except Exception as e:
        report["overall_status"] = "FAIL"
        report["errors"].append(f"Connection failed: {str(e)}")
        
        err_msg = str(e).lower()
        remediation_cmd = "Check database hostname, port, SID/Service Name, username, password, Oracle listener status, and network route."
        if any(term in err_msg for term in ["timeout", "timed out", "unreachable", "can't connect", "lost connection"]):
            remediation_cmd = (
                f"Connection timed out. If your target database is in GCP, verify firewall configuration. "
                f"You can authorize access on your target network by running:\n"
                f"`gcloud compute firewall-rules create allow-oracle-migration-ingress "
                f"--direction=INGRESS --priority=1000 --action=ALLOW "
                f"--rules=tcp:{port} --source-ranges=<GCP_SUBNET_OR_IP_RANGE>`"
            )
            
        report["checks"].append({
            "category": "Connectivity",
            "name": "Database Connection",
            "status": "FAIL",
            "message": f"Unable to connect to source Oracle database at {host}:{port}/{database}.",
            "details": str(e),
            "remediation": remediation_cmd
        })
        return report

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
            report["overall_status"] = "FAIL"
        elif status == "WARNING" and report["overall_status"] != "FAIL":
            report["overall_status"] = "WARNING"

    try:
        # 1. Check Oracle Version
        cursor.execute("SELECT version FROM v$instance")
        row = cursor.fetchone()
        version_str = row[0] if row else "unknown"
        
        # Parse version major
        version_match = re.match(r"^(\d+)", version_str)
        major_version = int(version_match.group(1)) if version_match else 0
        
        add_check(
            category="Version",
            name="Oracle Version Check",
            status="PASS" if major_version >= 12 else "WARNING" if major_version >= 11 else "FAIL",
            message=f"Source Oracle version is {version_str}.",
            details={"version": version_str, "major_version": major_version},
            remediation="Ensure target database version supports the converted schema. Oracle versions < 11.2 are not supported by modern Cloud databases / replication tools."
        )

        is_cdc = "CDC" in migration_type or "Online" in migration_type

        # 2. Check Archive Log Mode (Required for CDC)
        if is_cdc:
            cursor.execute("SELECT log_mode FROM v$database")
            db_row = cursor.fetchone()
            log_mode = db_row[0] if db_row else "UNKNOWN"
            
            add_check(
                category="CDC Configuration",
                name="Archive Log Mode Check",
                status="PASS" if log_mode.upper() == "ARCHIVELOG" else "FAIL",
                message=f"Database log mode is set to {log_mode}.",
                details={"log_mode": log_mode},
                remediation="Enable ARCHIVELOG mode on the Oracle database: run `ALTER DATABASE ARCHIVELOG;` in MOUNT status."
            )

            # 3. Check Supplemental Logging (Required for LogMiner CDC)
            cursor.execute("SELECT supplemental_log_data_min FROM v$database")
            supp_row = cursor.fetchone()
            supp_val = supp_row[0] if supp_row else "NO"
            
            add_check(
                category="CDC Configuration",
                name="Minimal Supplemental Logging Check",
                status="PASS" if supp_val.upper() in ["YES", "IMPLICIT"] else "FAIL",
                message=f"Minimal Supplemental Logging is set to {supp_val}.",
                details={"supplemental_log_data_min": supp_val},
                remediation="Enable minimal supplemental logging: `ALTER DATABASE ADD SUPPLEMENTAL LOG DATA;`"
            )

        # 4. Check User Privileges
        # Try to query session privileges to see what grants the user has
        cursor.execute("SELECT privilege FROM session_privs")
        user_privs = {r[0] for r in cursor.fetchall()}
        
        required_privs = {
            "CREATE SESSION": "Required to log in to database.",
            "SELECT ANY TABLE": "Required to query schema tables for replication.",
        }
        
        # LogMiner specific privileges for CDC
        if is_cdc:
            required_privs["SELECT ANY TRANSACTION"] = "Required for LogMiner transaction tracking."
            required_privs["SELECT ANY DICTIONARY"] = "Required to query system catalog views."
        
        missing_privs = [p for p in required_privs if p not in user_privs]
        
        priv_status = "PASS"
        priv_msg = "Migration user has correct system privileges."
        remediation_priv = ""
        
        if missing_privs:
            priv_status = "FAIL"
            priv_msg = f"Migration user is missing system privileges: {', '.join(missing_privs)}"
            remediation_priv = f"Grant missing system privileges: `GRANT {', '.join(missing_privs)} TO {user};`"
            
        add_check(
            category="Security & Privileges",
            name="Database User Privileges Check",
            status=priv_status,
            message=priv_msg,
            details={"privileges": list(user_privs), "missing": missing_privs},
            remediation=remediation_priv
        )

        # 5. Check Database Size
        try:
            cursor.execute("SELECT SUM(bytes) FROM dba_data_files")
            bytes_row = cursor.fetchone()
            total_bytes = bytes_row[0] if bytes_row and bytes_row[0] is not None else 0
            size_gb = total_bytes / (1024 * 1024 * 1024)
            
            add_check(
                category="Scale & Capacity",
                name="Database Size Check",
                status="PASS" if size_gb < 1000 else "WARNING",
                message=f"Database size is {size_gb:.2f} GB.",
                details={"total_bytes": total_bytes, "size_gb": size_gb},
                remediation="Ensure target GCP instance has sufficient storage capacity allocated."
            )
        except Exception as e:
            add_check(
                category="Scale & Capacity",
                name="Database Size Check",
                status="WARNING",
                message="Unable to verify database size (insufficient privileges to query dba_data_files).",
                details=str(e),
                remediation="Grant select access to DBA_DATA_FILES or SELECT ANY DICTIONARY to the migration user."
            )

        # 6. Source Database Load & Lock Risk Check
        lock_waits = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM v$session WHERE blocking_session IS NOT NULL")
            lock_row = cursor.fetchone()
            lock_waits = lock_row[0] if lock_row else 0
        except Exception:
            pass
            
        active_connections = 0
        max_connections = 150
        try:
            cursor.execute("SELECT (SELECT value FROM v$parameter WHERE name = 'sessions') as max_sess, (SELECT count(*) FROM v$session) as active_sess FROM dual")
            conn_row = cursor.fetchone()
            if conn_row:
                max_connections = int(conn_row[0])
                active_connections = int(conn_row[1])
        except Exception:
            pass
            
        conn_utilization = (active_connections / max_connections) * 100 if max_connections > 0 else 0
        
        load_status = "PASS"
        load_msg = f"Database active load is stable ({active_connections} active sessions, {lock_waits} blocked sessions)."
        load_remediation = ""
        
        if lock_waits > 0:
            load_status = "WARNING"
            load_msg = f"Detected {lock_waits} blocked transaction session(s) in Oracle."
            load_remediation = "Warning: Blocked database sessions are active. LogMiner / replication processes could experience delays. Check locks or run migration during off-peak hours."
        elif conn_utilization > 80:
            load_status = "WARNING"
            load_msg = f"High session utilization: {active_connections} active / {max_connections} max sessions ({conn_utilization:.1f}%)."
            load_remediation = "Warning: High session load on Oracle. Throttle client workload or schedule the migration snapshot during a low-traffic window."

        add_check(
            category="Source Database Health",
            name="Active Database Load & Lock Check",
            status=load_status,
            message=load_msg,
            details={
                "active_sessions": active_connections,
                "max_sessions": max_connections,
                "session_utilization_pct": conn_utilization,
                "blocked_sessions": lock_waits
            },
            remediation=load_remediation
        )

        # 7. Optimal Target Instance Sizer (Oracle to Cloud SQL/AlloyDB)
        target_sizer_status = "INFO"
        size_gb_val = size_gb if 'size_gb' in locals() else 0.0
        
        if size_gb_val < 50:
            rec_instance = "db-custom-2-7680 (2 vCPU, 7.5 GB RAM)"
            rec_disk = "50 GB (SSD)"
        elif size_gb_val < 200:
            rec_instance = "db-custom-4-15360 (4 vCPU, 15 GB RAM)"
            rec_disk = "200 GB (SSD)"
        elif size_gb_val < 1000:
            rec_instance = "db-custom-8-30720 (8 vCPU, 30 GB RAM)"
            rec_disk = "1000 GB (SSD, High-Performance)"
        else:
            rec_instance = "db-custom-16-61440 (16 vCPU, 60 GB RAM) or AlloyDB"
            rec_disk = f"{int(size_gb_val * 1.2)} GB (SSD, High-Performance)"
            
        if max_connections > 500:
            rec_instance += " - Recommended Memory scale-up for high sessions."

        sizer_msg = f"Recommended Target Database Sizing: Instance: {rec_instance}, Disk: {rec_disk}."
        
        add_check(
            category="Scale & Capacity",
            name="Optimal Target Instance Sizing",
            status=target_sizer_status,
            message=sizer_msg,
            details={
                "source_database_size_gb": size_gb_val,
                "source_max_sessions": max_connections,
                "recommended_target_instance": rec_instance,
                "recommended_target_disk": rec_disk
            },
            remediation="Provision target Cloud SQL for PostgreSQL / AlloyDB / Oracle instance with the recommended parameters or higher to prevent replication delays."
        )

        conn.close()
    except Exception as e:
        report["overall_status"] = "FAIL"
        report["errors"].append(f"Diagnostics query error: {str(e)}")
        add_check(
            category="Diagnostics Check",
            name="Run Diagnostics Query",
            status="FAIL",
            message="Failed to execute diagnostic queries.",
            details=str(e),
            remediation="Ensure the Oracle migration user has CREATE SESSION and SELECT ANY DICTIONARY privileges."
        )

    return report
