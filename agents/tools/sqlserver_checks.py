import pymssql
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
    if "database.windows.net" in host_lower:
        return "AZURE"
    if "rds.amazonaws.com" in host_lower:
        return "AWS"
    return "ON_PREMISE"

def check_sqlserver_readiness(
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 1433,
    cloud_provider: Optional[str] = None,
    migration_type: str = "Online CDC",
    auto_remediate: bool = False
) -> Dict[str, Any]:
    """
    Performs a comprehensive set of pre-migration checks on the source SQL Server database.
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
    
    # Establish connection
    try:
        conn = pymssql.connect(
            server=host,
            user=user,
            password=password,
            database=database,
            port=port,
            timeout=10
        )
        cursor = conn.cursor(as_dict=True)
        report["connection_status"] = "SUCCESS"
    except Exception as e:
        report["overall_status"] = "FAIL"
        report["errors"].append(f"Connection failed: {str(e)}")
        
        err_msg = str(e).lower()
        remediation_cmd = "Check database hostname, port, username, password, firewall rules, and VPC routing."
        if any(term in err_msg for term in ["timeout", "timed out", "unreachable", "can't connect", "lost connection"]):
            remediation_cmd = (
                f"Connection timed out. If your target database is in GCP, verify firewall configuration. "
                f"You can authorize access on your target network by running:\n"
                f"`gcloud compute firewall-rules create allow-mssql-migration-ingress "
                f"--direction=INGRESS --priority=1000 --action=ALLOW "
                f"--rules=tcp:{port} --source-ranges=<GCP_SUBNET_OR_IP_RANGE>`"
            )
            
        report["checks"].append({
            "category": "Connectivity",
            "name": "Database Connection",
            "status": "FAIL",
            "message": f"Unable to connect to source database at {host}:{port}.",
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
        # 1. Check SQL Server Version
        cursor.execute("SELECT @@VERSION as version;")
        row = cursor.fetchone()
        version_str = row["version"] if row else "unknown"
        
        # Parse version year
        version_match = re.search(r"SQL Server (\d{4})", version_str)
        version_year = int(version_match.group(1)) if version_match else 0
        
        add_check(
            category="Version",
            name="SQL Server Version Check",
            status="PASS" if version_year >= 2012 else "FAIL",
            message=f"Source SQL Server version is {version_str.splitlines()[0]}.",
            details={"version": version_str, "version_year": version_year},
            remediation="Ensure target database version is equal to or greater than the source version. SQL Server versions < 2012 are not supported by modern Cloud databases / replication tools."
        )

        is_cdc = "CDC" in migration_type or "Online" in migration_type
        
        # 2. Check if CDC is enabled on database (only for Online CDC)
        if is_cdc:
            cursor.execute(f"SELECT is_cdc_enabled FROM sys.databases WHERE name = DB_NAME();")
            cdc_row = cursor.fetchone()
            is_cdc_enabled = bool(cdc_row["is_cdc_enabled"]) if cdc_row else False
            
            add_check(
                category="CDC Configuration",
                name="Database CDC Enabled Check",
                status="PASS" if is_cdc_enabled else "FAIL",
                message=f"Change Data Capture (CDC) is {'enabled' if is_cdc_enabled else 'disabled'} on database.",
                details={"is_cdc_enabled": is_cdc_enabled},
                remediation="Enable CDC on the database: `EXEC sys.sp_cdc_enable_db;`"
            )
            
            # Check if any user tables do not have CDC enabled (if CDC is enabled on database)
            if is_cdc_enabled:
                cursor.execute("""
                    SELECT name 
                    FROM sys.tables 
                    WHERE is_tracked_by_cdc = 0 
                      AND is_ms_shipped = 0;
                """)
                no_cdc_tables = [r["name"] for r in cursor.fetchall()]
                
                status = "PASS" if not no_cdc_tables else "WARNING"
                msg = "All user tables are tracked by CDC." if not no_cdc_tables else f"Found {len(no_cdc_tables)} user table(s) not tracked by CDC."
                
                add_check(
                    category="CDC Configuration",
                    name="Table CDC Enabled Check",
                    status=status,
                    message=msg,
                    details={"tables_without_cdc": no_cdc_tables},
                    remediation="Enable CDC for each user table to replicate: `EXEC sys.sp_cdc_enable_table @source_schema = N'dbo', @source_name = N'table_name', @role_name = NULL;`"
                )

            # 3. Check SQL Server Agent status
            try:
                cursor.execute("SELECT status_desc FROM sys.dm_server_services WHERE service_to_run = 'SQL Server Agent';")
                agent_row = cursor.fetchone()
                agent_status = agent_row["status_desc"] if agent_row else "UNKNOWN"
                add_check(
                    category="CDC Service",
                    name="SQL Server Agent Service Status",
                    status="PASS" if agent_status.upper() == "RUNNING" else "FAIL",
                    message=f"SQL Server Agent service status is: {agent_status}.",
                    details={"service_status": agent_status},
                    remediation="Start the SQL Server Agent service. It is required for SQL Server CDC capture/cleanup jobs to run."
                )
            except Exception as e:
                # dm_server_services query may fail due to VIEW SERVER STATE permission
                add_check(
                    category="CDC Service",
                    name="SQL Server Agent Status Check",
                    status="WARNING",
                    message="Unable to verify SQL Server Agent status (requires VIEW SERVER STATE permission).",
                    details=str(e),
                    remediation="Ensure SQL Server Agent is running. CDC requires SQL Server Agent to capture changes."
                )

        # 4. Check User Roles
        cursor.execute("SELECT IS_SRVROLEMEMBER('sysadmin') as is_sysadmin, IS_MEMBER('db_owner') as is_db_owner;")
        role_row = cursor.fetchone()
        is_sysadmin = bool(role_row["is_sysadmin"]) if role_row else False
        is_db_owner = bool(role_row["is_db_owner"]) if role_row else False
        
        priv_status = "PASS"
        priv_msg = "Migration user has correct privileges."
        remediation_role = ""
        
        if not (is_sysadmin or is_db_owner):
            priv_status = "FAIL"
            priv_msg = "Migration user is not sysadmin or db_owner. Required for schema dump and CDC management."
            remediation_role = f"Add user to db_owner role: `ALTER ROLE db_owner ADD MEMBER {user};`"
            
        add_check(
            category="Security & Privileges",
            name="Database User Role Check",
            status=priv_status,
            message=priv_msg,
            details={"is_sysadmin": is_sysadmin, "is_db_owner": is_db_owner},
            remediation=remediation_role
        )

        # 5. Check Database Size
        cursor.execute("SELECT SUM(size) * 8 / 1024 AS size_mb FROM sys.master_files WHERE database_id = DB_ID();")
        size_row = cursor.fetchone()
        size_mb = float(size_row["size_mb"]) if size_row else 0.0
        size_gb = size_mb / 1024.0
        
        add_check(
            category="Scale & Capacity",
            name="Database Size Check",
            status="PASS" if size_gb < 1000 else "WARNING",
            message=f"Database size is {size_gb:.2f} GB.",
            details={"size_mb": size_mb, "size_gb": size_gb},
            remediation="Ensure target Cloud SQL instance has sufficient storage capacity allocated."
        )

        # 6. Source Database Load & Lock Risk Check
        lock_waits = 0
        try:
            cursor.execute("SELECT COUNT(*) as lock_waits FROM sys.dm_tran_locks WHERE request_status = 'WAIT';")
            lock_row = cursor.fetchone()
            lock_waits = int(lock_row["lock_waits"]) if lock_row else 0
        except Exception:
            pass
            
        active_connections = 0
        max_connections = 100
        try:
            cursor.execute("SELECT @@MAX_CONNECTIONS as max_conns, (SELECT COUNT(dbid) FROM sys.sysprocesses) as active_conns;")
            conn_row = cursor.fetchone()
            if conn_row:
                active_connections = int(conn_row["active_conns"])
                max_connections = int(conn_row["max_conns"])
        except Exception:
            pass
            
        conn_utilization = (active_connections / max_connections) * 100 if max_connections > 0 else 0
        
        load_status = "PASS"
        load_msg = f"Database active load is stable ({active_connections} active connections, {lock_waits} lock requests waiting)."
        load_remediation = ""
        
        if lock_waits > 0:
            load_status = "WARNING"
            load_msg = f"Detected {lock_waits} transactions waiting for locks in SQL Server."
            load_remediation = "Warning: Active transaction locks are waiting. CDC snapshot processing might increase blocking. Resolve lock contention or schedule migration during low load."
        elif conn_utilization > 80:
            load_status = "WARNING"
            load_msg = f"High connection utilization: {active_connections} active / {max_connections} max connections ({conn_utilization:.1f}%)."
            load_remediation = "Warning: High active connections on SQL Server. Throttle client connection rate or schedule migration during off-peak hours."

        add_check(
            category="Source Database Health",
            name="Active Database Load & Lock Check",
            status=load_status,
            message=load_msg,
            details={
                "active_connections": active_connections,
                "max_connections": max_connections,
                "connection_utilization_pct": conn_utilization,
                "blocked_locks": lock_waits
            },
            remediation=load_remediation
        )

        # 7. Optimal Target Instance Sizer (SQL Server)
        target_sizer_status = "INFO"
        
        if size_gb < 50:
            rec_instance = "db-custom-2-7680 (2 vCPU, 7.5 GB RAM)"
            rec_disk = "50 GB (SSD)"
        elif size_gb < 200:
            rec_instance = "db-custom-4-15360 (4 vCPU, 15 GB RAM)"
            rec_disk = "200 GB (SSD)"
        elif size_gb < 1000:
            rec_instance = "db-custom-8-30720 (8 vCPU, 30 GB RAM)"
            rec_disk = "1000 GB (SSD, High-Performance)"
        else:
            rec_instance = "db-custom-16-61440 (16 vCPU, 60 GB RAM)"
            rec_disk = f"{int(size_gb * 1.2)} GB (SSD, High-Performance)"
            
        if max_connections > 500:
            rec_instance += " - Recommended Memory scale-up for high active sessions."

        sizer_msg = f"Recommended Target Database Sizing: Instance: {rec_instance}, Disk: {rec_disk}."
        
        add_check(
            category="Scale & Capacity",
            name="Optimal Target Instance Sizing",
            status=target_sizer_status,
            message=sizer_msg,
            details={
                "source_database_size_gb": size_gb,
                "source_max_connections": max_connections,
                "recommended_target_instance": rec_instance,
                "recommended_target_disk": rec_disk
            },
            remediation="Provision target Cloud SQL for SQL Server instance with the recommended parameters or higher to prevent CDC replication lag."
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
            remediation="Ensure the database migration user has SELECT access to sys schemas and VIEW DATABASE STATE permissions."
        )

    return report
