import pg8000.dbapi
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
    if "rds.amazonaws.com" in host_lower or "rds.amazon" in host_lower:
        return "AWS"
    if "database.azure.com" in host_lower:
        return "AZURE"
    return "ON_PREMISE"

def check_postgres_readiness(
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 5432,
    cloud_provider: Optional[str] = None,
    migration_type: str = "Online CDC",
    auto_remediate: bool = False
) -> Dict[str, Any]:
    """
    Performs a comprehensive set of pre-migration checks on the source PostgreSQL database.
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
        conn = pg8000.dbapi.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            timeout=10
        )
        cursor = conn.cursor()
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
                f"`gcloud compute firewall-rules create allow-postgres-migration-ingress "
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
        if status.startswith("PASS"):
            pass
        elif status == "FAIL":
            report["overall_status"] = "FAIL"
        elif status == "WARNING" and report["overall_status"] != "FAIL":
            report["overall_status"] = "WARNING"

    def try_execute(query: str) -> bool:
        try:
            cursor.execute(query)
            conn.commit()
            return True
        except Exception as e:
            report["errors"].append(f"Remediation statement failed: {query}. Error: {str(e)}")
            return False

    try:
        # 1. Check PostgreSQL Version
        cursor.execute("SHOW server_version;")
        row = cursor.fetchone()
        version_str = row[0] if row else "unknown"
        # Parse version major
        version_match = re.match(r"^(\d+)", version_str)
        major_version = 0
        if version_match:
            major_version = int(version_match.group(1))
            
        add_check(
            category="Version",
            name="PostgreSQL Version Check",
            status="PASS" if major_version >= 10 else "WARNING" if major_version >= 9.6 else "FAIL",
            message=f"Source PostgreSQL version is {version_str}.",
            details={"version": version_str, "major_version": major_version},
            remediation="Ensure target database version is equal to or greater than the source version. PostgreSQL versions < 9.6 are not supported by modern Cloud databases / logical replication tools."
        )

        # 2. Check Logical Replication Parameters (only for Online CDC)
        is_cdc = "CDC" in migration_type or "Online" in migration_type
        
        if is_cdc:
            # Check wal_level
            cursor.execute("SHOW wal_level;")
            wal_level = cursor.fetchone()[0]
            add_check(
                category="Replication Configuration",
                name="WAL Level Check (wal_level)",
                status="PASS" if wal_level.lower() == "logical" else "FAIL",
                message=f"wal_level is set to {wal_level}.",
                details={"value": wal_level},
                remediation="Set `wal_level = logical` in postgresql.conf or AWS DB Parameter Group. Reboot is required."
            )
            
            # Check max_replication_slots
            cursor.execute("SHOW max_replication_slots;")
            slots_val = int(cursor.fetchone()[0])
            add_check(
                category="Replication Configuration",
                name="Max Replication Slots Check",
                status="PASS" if slots_val >= 1 else "FAIL",
                message=f"max_replication_slots is set to {slots_val}.",
                details={"value": slots_val},
                remediation="Set `max_replication_slots` to at least 1 (recommended >= 5) in configurations. Reboot is required."
            )

            # Check max_wal_senders
            cursor.execute("SHOW max_wal_senders;")
            senders_val = int(cursor.fetchone()[0])
            add_check(
                category="Replication Configuration",
                name="Max WAL Senders Check",
                status="PASS" if senders_val >= 1 else "FAIL",
                message=f"max_wal_senders is set to {senders_val}.",
                details={"value": senders_val},
                remediation="Set `max_wal_senders` to at least 1 (recommended >= 10) in configurations. Reboot is required."
            )

        # 3. Check User Privileges
        cursor.execute("SELECT rolreplication, rolsuper FROM pg_roles WHERE rolname = CURRENT_USER;")
        role_row = cursor.fetchone()
        has_repl = role_row[0] if role_row else False
        has_super = role_row[1] if role_row else False
        
        priv_status = "PASS"
        priv_msg = "Migration user has correct privileges."
        remediation_text = ""
        
        if not (has_repl or has_super):
            if provider == "AWS":
                priv_status = "WARNING"
                priv_msg = "Migration user does not have direct REPLICATION or superuser role. Ensure user has 'rds_superuser' or 'rds_replication' membership."
                remediation_text = f"Grant rds_replication role: `GRANT rds_replication TO {user};`"
            else:
                priv_status = "FAIL"
                priv_msg = "Migration user is missing REPLICATION privilege."
                remediation_text = f"Alter user to replication: `ALTER USER {user} WITH REPLICATION;`"

        add_check(
            category="Security & Privileges",
            name="Database User Replication Privilege Check",
            status=priv_status,
            message=priv_msg,
            details={"rolreplication": has_repl, "rolsuper": has_super},
            remediation=remediation_text
        )

        # 4. Check Tables Without Primary Keys
        cursor.execute(f"""
            SELECT c.relname
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_index i ON i.indrelid = c.oid AND i.indisprimary = true
            WHERE n.nspname = 'public'
              AND c.relkind = 'r'
              AND i.indisprimary IS NULL;
        """)
        no_pk_tables = [row[0] for row in cursor.fetchall()]
        
        pk_status = "PASS"
        pk_msg = "All user tables in public schema have a Primary Key defined."
        remediation_pk = ""
        
        if no_pk_tables:
            pk_status = "WARNING"
            pk_msg = f"Found {len(no_pk_tables)} table(s) in public schema without a primary key."
            remediation_pk = "Add primary keys to tables, or configure `REPLICA IDENTITY FULL` on these tables so logical replication can track updates/deletes."

        add_check(
            category="Database Schema",
            name="Primary Key Check",
            status=pk_status,
            message=pk_msg,
            details={"tables_without_primary_key": no_pk_tables},
            remediation=remediation_pk
        )

        # 5. Check Database Size
        cursor.execute(f"SELECT pg_database_size('{database}');")
        size_bytes = cursor.fetchone()[0]
        size_gb = size_bytes / (1024 * 1024 * 1024)
        
        add_check(
            category="Scale & Capacity",
            name="Database Size Check",
            status="PASS" if size_gb < 1000 else "WARNING",
            message=f"Database size is {size_gb:.2f} GB.",
            details={"size_bytes": size_bytes, "size_gb": size_gb},
            remediation="Ensure target instance disk size is configured to handle database volume. Large databases may require allocating more storage and IOPS."
        )

        # 6. Source Database Load & Lock Risk Check
        lock_waits = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM pg_locks WHERE NOT granted;")
            lock_row = cursor.fetchone()
            lock_waits = lock_row[0] if lock_row else 0
        except Exception:
            pass
            
        active_connections = 0
        max_connections = 100
        try:
            cursor.execute("SELECT (SELECT count(*) FROM pg_stat_activity) as active_conns, current_setting('max_connections')::int as max_conns;")
            conn_row = cursor.fetchone()
            if conn_row:
                active_connections = conn_row[0]
                max_connections = conn_row[1]
        except Exception:
            pass
            
        conn_utilization = (active_connections / max_connections) * 100 if max_connections > 0 else 0
        
        load_status = "PASS"
        load_msg = f"Database active load is stable ({active_connections} active connections, {lock_waits} blocked locks)."
        load_remediation = ""
        
        if lock_waits > 0:
            load_status = "WARNING"
            load_msg = f"Detected {lock_waits} blocked transaction locks in PostgreSQL."
            load_remediation = "Warning: Blocked locks are present. Logical replication snapshots might experience delay or cause lock contention. Resolve blocking locks or run migration during low load."
        elif conn_utilization > 80:
            load_status = "WARNING"
            load_msg = f"High connection utilization: {active_connections} active / {max_connections} max connections ({conn_utilization:.1f}%)."
            load_remediation = "Warning: High active connections on Postgres. Throttle client connection rate or schedule migration during off-peak hours."

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

        # 7. Optimal Target Instance Sizer (PostgreSQL)
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
            rec_instance = "db-custom-16-61440 (16 vCPU, 60 GB RAM) or AlloyDB"
            rec_disk = f"{int(size_gb * 1.2)} GB (SSD, High-Performance)"
            
        if max_connections > 500:
            rec_instance += " - Recommended Memory scale-up for high connections. Consider PgBouncer."

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
            remediation="Provision target Cloud SQL for PostgreSQL / AlloyDB instance with the recommended parameters or higher to prevent CDC replication lag."
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
            remediation="Ensure the user has sufficient permissions to access server settings and schema catalogs."
        )

    def sanitize_decimals(val: Any) -> Any:
        import decimal
        if isinstance(val, decimal.Decimal):
            if val % 1 == 0:
                return int(val)
            return float(val)
        elif isinstance(val, dict):
            return {k: sanitize_decimals(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [sanitize_decimals(item) for item in val]
        return val

    return sanitize_decimals(report)
