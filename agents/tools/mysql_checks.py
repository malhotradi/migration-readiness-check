import mysql.connector
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

def check_mysql_readiness(
    host: str,
    user: str,
    password: str,
    database: str,
    port: int = 3306,
    cloud_provider: Optional[str] = None,
    migration_type: str = "Online CDC",
    auto_remediate: bool = False
) -> Dict[str, Any]:
    """
    Performs a comprehensive set of pre-migration checks on the source MySQL database.
    Optionally auto-remediates fixable configuration parameters.
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
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            connect_timeout=10
        )
        cursor = conn.cursor(dictionary=True)
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
                f"`gcloud compute firewall-rules create allow-db-migration-ingress "
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

    # Define a helper to add checks to the list and update overall status
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
            if not cursor.with_rows:
                conn.commit()
            return True
        except Exception as e:
            report["errors"].append(f"Remediation statement failed: {query}. Error: {str(e)}")
            return False

    try:
        # 1. Check MySQL Version
        cursor.execute("SELECT VERSION() as version;")
        row = cursor.fetchone()
        version_str = row["version"] if row else "unknown"
        # Parse version major
        version_match = re.match(r"^(\d+)\.(\d+)", version_str)
        major_version = 0.0
        if version_match:
            major_version = float(f"{version_match.group(1)}.{version_match.group(2)}")
            
        add_check(
            category="Version",
            name="MySQL Version Check",
            status="PASS" if major_version >= 5.7 else "FAIL",
            message=f"Source MySQL version is {version_str}.",
            details={"version": version_str, "major_version": major_version},
            remediation="Ensure target database version is equal to or greater than the source version. MySQL versions < 5.7 are not supported by modern Cloud databases / replication tools."
        )

        # 2. Check Global Variables
        target_vars = [
            "log_bin",
            "binlog_format",
            "binlog_row_image",
            "gtid_mode",
            "enforce_gtid_consistency",
            "server_id",
            "lower_case_table_names"
        ]
        cursor.execute("SHOW GLOBAL VARIABLES;")
        all_vars = {row["Variable_name"]: row["Value"] for row in cursor.fetchall()}
        
        is_offline = "offline" in migration_type.lower() or "dump" in migration_type.lower()

        # log_bin
        log_bin_val = all_vars.get("log_bin", "OFF")
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="Binary Logging Enabled (log_bin)",
                status="PASS",
                message="Binary logging check bypassed (not required for offline migration).",
                details={"value": log_bin_val}
            )
        else:
            add_check(
                category="Configuration Flags",
                name="Binary Logging Enabled (log_bin)",
                status="PASS" if log_bin_val.upper() in ["ON", "1"] else "FAIL",
                message=f"Binary logging is {log_bin_val}.",
                details={"value": log_bin_val},
                remediation="Enable binary logging (`log_bin = ON` in my.cnf or parameter group). For RDS, enable automated backups."
            )

        # binlog_format
        binlog_format_val = all_vars.get("binlog_format", "")
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="Binlog Format (binlog_format)",
                status="PASS",
                message="Binlog format check bypassed (not required for offline migration).",
                details={"value": binlog_format_val}
            )
        elif binlog_format_val.upper() != "ROW" and auto_remediate and provider != "AWS":
            if try_execute("SET GLOBAL binlog_format = 'ROW';"):
                binlog_format_val = "ROW"
                add_check(
                    category="Configuration Flags",
                    name="Binlog Format (binlog_format)",
                    status="PASS (Auto-Remediated)",
                    message="Binlog format has been auto-remediated to ROW.",
                    details={"value": "ROW"}
                )
            else:
                add_check(
                    category="Configuration Flags",
                    name="Binlog Format (binlog_format)",
                    status="FAIL",
                    message=f"Binlog format is set to {binlog_format_val}.",
                    details={"value": binlog_format_val},
                    remediation="Set `binlog_format = ROW` in server configurations / Parameter Group."
                )
        else:
            add_check(
                category="Configuration Flags",
                name="Binlog Format (binlog_format)",
                status="PASS" if binlog_format_val.upper() == "ROW" else "FAIL",
                message=f"Binlog format is set to {binlog_format_val}.",
                details={"value": binlog_format_val},
                remediation="Set `binlog_format = ROW` in server configurations / Parameter Group."
            )

        # binlog_row_image
        binlog_row_image_val = all_vars.get("binlog_row_image", "FULL")
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="Binlog Row Image (binlog_row_image)",
                status="PASS",
                message="Binlog row image check bypassed (not required for offline migration).",
                details={"value": binlog_row_image_val}
            )
        elif binlog_row_image_val.upper() != "FULL" and auto_remediate and provider != "AWS":
            if try_execute("SET GLOBAL binlog_row_image = 'FULL';"):
                binlog_row_image_val = "FULL"
                add_check(
                    category="Configuration Flags",
                    name="Binlog Row Image (binlog_row_image)",
                    status="PASS (Auto-Remediated)",
                    message="Binlog row image has been auto-remediated to FULL.",
                    details={"value": "FULL"}
                )
            else:
                add_check(
                    category="Configuration Flags",
                    name="Binlog Row Image (binlog_row_image)",
                    status="WARNING",
                    message=f"Binlog row image is set to {binlog_row_image_val}.",
                    details={"value": binlog_row_image_val},
                    remediation="Set `binlog_row_image = FULL` to ensure that full row values are sent in replication logs, preventing sync failures."
                )
        else:
            add_check(
                category="Configuration Flags",
                name="Binlog Row Image (binlog_row_image)",
                status="PASS" if binlog_row_image_val.upper() == "FULL" else "WARNING",
                message=f"Binlog row image is set to {binlog_row_image_val}.",
                details={"value": binlog_row_image_val},
                remediation="Set `binlog_row_image = FULL` to ensure that full row values are sent in replication logs, preventing sync failures."
            )

        # enforce_gtid_consistency
        enforce_gtid_val = all_vars.get("enforce_gtid_consistency", "OFF")
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="Enforce GTID Consistency (enforce_gtid_consistency)",
                status="PASS",
                message="Enforce GTID consistency check bypassed (not required for offline migration).",
                details={"value": enforce_gtid_val}
            )
        elif enforce_gtid_val.upper() not in ["ON", "1"] and auto_remediate and provider != "AWS":
            if try_execute("SET GLOBAL enforce_gtid_consistency = 'ON';"):
                enforce_gtid_val = "ON"
                add_check(
                    category="Configuration Flags",
                    name="Enforce GTID Consistency (enforce_gtid_consistency)",
                    status="PASS (Auto-Remediated)",
                    message="Enforce GTID consistency has been auto-remediated to ON.",
                    details={"value": "ON"}
                )
            else:
                add_check(
                    category="Configuration Flags",
                    name="Enforce GTID Consistency (enforce_gtid_consistency)",
                    status="FAIL",
                    message=f"Enforce GTID consistency is {enforce_gtid_val}.",
                    details={"value": enforce_gtid_val},
                    remediation="Set `enforce_gtid_consistency = ON` in server configurations / Parameter Group."
                )
        else:
            add_check(
                category="Configuration Flags",
                name="Enforce GTID Consistency (enforce_gtid_consistency)",
                status="PASS" if enforce_gtid_val.upper() in ["ON", "1"] else "FAIL",
                message=f"Enforce GTID consistency is {enforce_gtid_val}.",
                details={"value": enforce_gtid_val},
                remediation="Set `enforce_gtid_consistency = ON` in server configurations / Parameter Group."
            )

        # gtid_mode
        gtid_mode_val = all_vars.get("gtid_mode", "OFF")
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="GTID Mode (gtid_mode)",
                status="PASS",
                message="GTID mode check bypassed (not required for offline migration).",
                details={"value": gtid_mode_val}
            )
        elif gtid_mode_val.upper() != "ON" and auto_remediate and provider != "AWS" and enforce_gtid_val.upper() in ["ON", "1"]:
            seq_success = True
            for mode in ["OFF_PERMISSIVE", "ON_PERMISSIVE", "ON"]:
                if not try_execute(f"SET GLOBAL gtid_mode = '{mode}';"):
                    seq_success = False
                    break
            if seq_success:
                gtid_mode_val = "ON"
                add_check(
                    category="Configuration Flags",
                    name="GTID Mode (gtid_mode)",
                    status="PASS (Auto-Remediated)",
                    message="GTID mode has been auto-remediated to ON.",
                    details={"value": "ON"}
                )
            else:
                add_check(
                    category="Configuration Flags",
                    name="GTID Mode (gtid_mode)",
                    status="FAIL",
                    message=f"GTID mode is set to {gtid_mode_val}.",
                    details={"value": gtid_mode_val},
                    remediation="Set `gtid_mode = ON` in server configurations / Parameter Group. Logical replication / CDC tools require GTID to be enabled."
                )
        else:
            add_check(
                category="Configuration Flags",
                name="GTID Mode (gtid_mode)",
                status="PASS" if gtid_mode_val.upper() == "ON" else "FAIL",
                message=f"GTID mode is set to {gtid_mode_val}.",
                details={"value": gtid_mode_val},
                remediation="Set `gtid_mode = ON` in server configurations / Parameter Group. Logical replication / CDC tools require GTID to be enabled."
            )

        # server_id
        server_id_val = int(all_vars.get("server_id", 0))
        if is_offline:
            add_check(
                category="Configuration Flags",
                name="Server ID Unique (server_id)",
                status="PASS",
                message="Server ID check bypassed (not required for offline migration).",
                details={"value": server_id_val}
            )
        else:
            add_check(
                category="Configuration Flags",
                name="Server ID Unique (server_id)",
                status="PASS" if server_id_val > 0 else "FAIL",
                message=f"Server ID is {server_id_val}.",
                details={"value": server_id_val},
                remediation="Set `server_id` to a unique positive integer value greater than 0."
            )

        # lower_case_table_names
        lctn_val = all_vars.get("lower_case_table_names", "0")
        add_check(
            category="Configuration Flags",
            name="Lower Case Table Names Check",
            status="INFO",
            message=f"lower_case_table_names is set to {lctn_val}.",
            details={"value": lctn_val},
            remediation="Ensure that the target Cloud SQL for MySQL is created with the exact same `lower_case_table_names` configuration value, as this cannot be changed after creation."
        )

        # 3. Check Binlog Retention Period
        retention_seconds = 0
        has_retention_check = False
        
        if is_offline:
            add_check(
                category="Binlog Retention",
                name="Binlog Retention Period",
                status="PASS",
                message="Binlog retention check bypassed (not required for offline migration).",
                details={}
            )
            has_retention_check = True
        
        if provider == "AWS":
            try:
                # Query RDS configurations
                cursor.execute("CALL mysql.rds_show_configuration;")
                rds_configs = cursor.fetchall()
                retention_hours = None
                for config in rds_configs:
                    if config.get("name") == "binlog retention hours":
                        retention_hours = int(config.get("value"))
                        break
                if retention_hours is not None:
                    has_retention_check = True
                    retention_seconds = retention_hours * 3600
                    if retention_hours < 24 and auto_remediate:
                        if try_execute("CALL mysql.rds_set_configuration('binlog retention hours', 72);"):
                            retention_hours = 72
                            retention_seconds = 72 * 3600
                            add_check(
                                category="Binlog Retention",
                                name="AWS RDS Binlog Retention Period",
                                status="PASS (Auto-Remediated)",
                                message="AWS RDS Binlog retention has been auto-remediated to 72 hours.",
                                details={"retention_hours": 72}
                            )
                        else:
                            add_check(
                                category="Binlog Retention",
                                name="AWS RDS Binlog Retention Period",
                                status="WARNING",
                                message=f"AWS RDS Binlog retention is set to {retention_hours} hours.",
                                details={"retention_hours": retention_hours},
                                remediation="Set binlog retention hours to at least 24 hours (preferably 72 hours) by running: `CALL mysql.rds_set_configuration('binlog retention hours', 72);`"
                            )
                    else:
                        status = "PASS" if retention_hours >= 24 else "WARNING"
                        add_check(
                            category="Binlog Retention",
                            name="AWS RDS Binlog Retention Period",
                            status=status,
                            message=f"AWS RDS Binlog retention is set to {retention_hours} hours.",
                            details={"retention_hours": retention_hours},
                            remediation="Set binlog retention hours to at least 24 hours (preferably 72 hours) by running: `CALL mysql.rds_set_configuration('binlog retention hours', 72);`"
                        )
            except Exception as e:
                report["errors"].append(f"Failed to check AWS RDS binlog configuration: {str(e)}")

        if not has_retention_check:
            # Generic/Azure binlog retention check via system variables
            expire_seconds = all_vars.get("binlog_expire_logs_seconds")
            expire_days = all_vars.get("expire_logs_days")
            
            if expire_seconds is not None:
                retention_seconds = int(expire_seconds)
                if retention_seconds < 86400 and auto_remediate:
                    if try_execute("SET GLOBAL binlog_expire_logs_seconds = 259200;"):
                        retention_seconds = 259200
                        add_check(
                            category="Binlog Retention",
                            name="Binlog Expire Seconds",
                            status="PASS (Auto-Remediated)",
                            message="Binlog expiration has been auto-remediated to 259200 seconds (72 hours).",
                            details={"binlog_expire_logs_seconds": 259200}
                        )
                    else:
                        add_check(
                            category="Binlog Retention",
                            name="Binlog Expire Seconds",
                            status="WARNING",
                            message=f"Binlog expiration is set to {retention_seconds} seconds.",
                            details={"binlog_expire_logs_seconds": retention_seconds},
                            remediation="Increase binlog retention (`binlog_expire_logs_seconds`) to at least 86400 seconds (1 day, 7 days recommended)."
                        )
                else:
                    status = "PASS" if retention_seconds >= 86400 else "WARNING"
                    add_check(
                        category="Binlog Retention",
                        name="Binlog Expire Seconds",
                        status=status,
                        message=f"Binlog expiration is set to {retention_seconds} seconds ({retention_seconds / 3600:.1f} hours).",
                        details={"binlog_expire_logs_seconds": retention_seconds},
                        remediation="Increase binlog retention (`binlog_expire_logs_seconds`) to at least 86400 seconds (1 day, 7 days recommended)."
                    )
            elif expire_days is not None:
                retention_seconds = int(expire_days) * 86400
                if int(expire_days) < 1 and auto_remediate:
                    if try_execute("SET GLOBAL expire_logs_days = 3;"):
                        expire_days = 3
                        retention_seconds = 3 * 86400
                        add_check(
                            category="Binlog Retention",
                            name="Binlog Expire Days (Deprecated)",
                            status="PASS (Auto-Remediated)",
                            message="Binlog expiration has been auto-remediated to 3 days.",
                            details={"expire_logs_days": 3}
                        )
                    else:
                        add_check(
                            category="Binlog Retention",
                            name="Binlog Expire Days (Deprecated)",
                            status="WARNING",
                            message=f"Binlog expiration is set to {expire_days} days.",
                            details={"expire_logs_days": int(expire_days)},
                            remediation="Increase binlog retention (`expire_logs_days`) to at least 1 day (7 days recommended)."
                        )
                else:
                    status = "PASS" if int(expire_days) >= 1 else "WARNING"
                    add_check(
                        category="Binlog Retention",
                        name="Binlog Expire Days (Deprecated)",
                        status=status,
                        message=f"Binlog expiration is set to {expire_days} days.",
                        details={"expire_logs_days": int(expire_days)},
                        remediation="Increase binlog retention (`expire_logs_days`) to at least 1 day (7 days recommended)."
                    )
            else:
                add_check(
                    category="Binlog Retention",
                    name="Binlog Expiration Settings",
                    status="WARNING",
                    message="Unable to determine binlog retention period. Global variables not found.",
                    details={},
                    remediation="Check my.cnf or database configuration parameters to verify that replication logs are stored for at least 24 hours."
                )

        # 4. Check Non-InnoDB Storage Engines
        engine_query = f"""
            SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = '{database}' 
              AND TABLE_TYPE = 'BASE TABLE'
              AND ENGINE <> 'InnoDB';
        """
        cursor.execute(engine_query)
        non_innodb_tables = cursor.fetchall()
        
        non_innodb_status = "PASS" if not non_innodb_tables else "WARNING"
        non_innodb_message = "All user tables use InnoDB storage engine." if not non_innodb_tables else f"Found {len(non_innodb_tables)} table(s) using non-InnoDB engines."
        
        add_check(
            category="Database Schema",
            name="Storage Engine Check",
            status=non_innodb_status,
            message=non_innodb_message,
            details={"non_innodb_tables": non_innodb_tables},
            remediation="Convert non-InnoDB tables to InnoDB before migration (e.g. `ALTER TABLE table_name ENGINE=InnoDB;`). Non-InnoDB tables can cause replica lag and inconsistency."
        )

        # 5. Check Tables Without Primary Keys
        pk_query = f"""
            SELECT t.TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES t
            LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc 
              ON t.TABLE_SCHEMA = tc.TABLE_SCHEMA 
              AND t.TABLE_NAME = tc.TABLE_NAME 
              AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            WHERE t.TABLE_SCHEMA = '{database}'
              AND t.TABLE_TYPE = 'BASE TABLE'
              AND tc.CONSTRAINT_TYPE IS NULL;
        """
        cursor.execute(pk_query)
        no_pk_tables = [row["TABLE_NAME"] for row in cursor.fetchall()]
        
        pk_status = "PASS" if not no_pk_tables else "WARNING"
        pk_message = "All user tables have a Primary Key defined." if not no_pk_tables else f"Found {len(no_pk_tables)} table(s) without a primary key."
        
        add_check(
            category="Database Schema",
            name="Primary Key Check",
            status=pk_status,
            message=pk_message,
            details={"tables_without_primary_key": no_pk_tables},
            remediation="Add a primary key or unique index to tables before migrating. Tables without primary keys can cause severe replication delays."
        )

        # 6. Check User Privileges
        cursor.execute("SHOW GRANTS;")
        grants = [row[list(row.keys())[0]] for row in cursor.fetchall()]
        grants_str = " ".join(grants).upper()
        
        if is_offline:
            required_grants = {
                "SELECT": "Required to read tables during snapshot / dump.",
                "RELOAD": "Required to perform lock tables for consistent dump."
            }
        else:
            required_grants = {
                "REPLICATION SLAVE": "Required to replicate binary logs.",
                "REPLICATION CLIENT": "Required to read binlog state and status.",
                "SELECT": "Required to read tables during snapshot.",
                "RELOAD": "Required to perform administration tasks like flush logs."
            }
        
        has_all_privileges = "ALL PRIVILEGES" in grants_str
        
        missing_grants = []
        for grant, reason in required_grants.items():
            if not has_all_privileges and grant not in grants_str:
                missing_grants.append(grant)
                
        # Also check optional grants (like LOCK TABLES, TRIGGER, EXECUTE, SHOW VIEW)
        optional_grants = {
            "SHOW VIEW": "Required if migrating view schemas.",
            "TRIGGER": "Required if migrating database triggers.",
            "EXECUTE": "Required if migrating stored procedures and functions."
        }
        missing_optional = []
        for grant, reason in optional_grants.items():
            if not has_all_privileges and grant not in grants_str:
                missing_optional.append(grant)
                
        if is_offline:
            remediation_sql = f"GRANT SELECT, RELOAD, SHOW VIEW, TRIGGER, EXECUTE ON *.* TO '{user}'@'%';"
        else:
            remediation_sql = f"GRANT REPLICATION SLAVE, REPLICATION CLIENT, SELECT, RELOAD, SHOW VIEW, TRIGGER, EXECUTE ON *.* TO '{user}'@'%';"
        
        priv_status = "PASS"
        priv_msg = "Migration user has all required and optional privileges."
        if missing_grants:
            if auto_remediate:
                if try_execute(remediation_sql) and try_execute("FLUSH PRIVILEGES;"):
                    priv_status = "PASS (Auto-Remediated)"
                    priv_msg = "Migration user was missing critical privileges, but they have been auto-remediated."
                    missing_grants = []
                else:
                    priv_status = "FAIL"
                    priv_msg = f"Migration user is missing critical privileges: {', '.join(missing_grants)}"
            else:
                priv_status = "FAIL"
                priv_msg = f"Migration user is missing critical privileges: {', '.join(missing_grants)}"
        elif missing_optional:
            if auto_remediate:
                if try_execute(remediation_sql) and try_execute("FLUSH PRIVILEGES;"):
                    priv_status = "PASS (Auto-Remediated)"
                    priv_msg = "Migration user was missing optional privileges, but they have been auto-remediated."
                    missing_optional = []
                else:
                    priv_status = "WARNING"
                    priv_msg = f"Migration user is missing optional privileges: {', '.join(missing_optional)}"
            else:
                priv_status = "WARNING"
                priv_msg = f"Migration user is missing optional privileges: {', '.join(missing_optional)}"
            
        add_check(
            category="Security & Privileges",
            name="Database User Privileges Check",
            status=priv_status,
            message=priv_msg,
            details={
                "grants": grants,
                "missing_required": missing_grants,
                "missing_optional": missing_optional,
                "has_all_privileges": has_all_privileges
            },
            remediation=f"Grant missing privileges to the migration user. Recommended command: `{remediation_sql}`" if missing_grants or missing_optional else ""
        )

        # 7. Check Definers
        definer_issues = []
        
        # View definers
        cursor.execute(f"""
            SELECT TABLE_NAME as name, DEFINER as definer, 'VIEW' as type 
            FROM INFORMATION_SCHEMA.VIEWS 
            WHERE TABLE_SCHEMA = '{database}';
        """)
        definer_issues.extend(cursor.fetchall())
        
        # Trigger definers
        cursor.execute(f"""
            SELECT TRIGGER_NAME as name, DEFINER as definer, 'TRIGGER' as type 
            FROM INFORMATION_SCHEMA.TRIGGERS 
            WHERE TRIGGER_SCHEMA = '{database}';
        """)
        definer_issues.extend(cursor.fetchall())

        # Routine definers
        cursor.execute(f"""
            SELECT ROUTINE_NAME as name, DEFINER as definer, ROUTINE_TYPE as type 
            FROM INFORMATION_SCHEMA.ROUTINES 
            WHERE ROUTINE_SCHEMA = '{database}';
        """)
        definer_issues.extend(cursor.fetchall())
        
        # Group issues by definer user
        definer_counts = {}
        for issue in definer_issues:
            definer = issue["definer"]
            definer_counts[definer] = definer_counts.get(definer, 0) + 1
            
        definer_status = "PASS"
        definer_msg = "All object definers are compatible or none found."
        if definer_counts:
            custom_definers = [d for d in definer_counts.keys() if user not in d]
            if custom_definers:
                definer_status = "WARNING"
                definer_msg = f"Found objects defined by {len(custom_definers)} other user(s) (e.g. {', '.join(custom_definers[:3])})."
                
        add_check(
            category="Database Schema",
            name="Definer Clauses Check",
            status=definer_status,
            message=definer_msg,
            details={"definers": definer_counts, "total_objects": len(definer_issues)},
            remediation="Objects (views/triggers/procedures) with definer parameters referencing users that won't exist on target might fail. Consider stripping or updating the DEFINER clause to the migration user or CURRENT_USER before migration."
        )

        # 8. Check Database Size & Table Metrics
        cursor.execute(f"""
            SELECT 
                SUM(DATA_LENGTH + INDEX_LENGTH) as total_bytes,
                COUNT(TABLE_NAME) as total_tables
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = '{database}' 
              AND TABLE_TYPE = 'BASE TABLE';
        """)
        db_metrics = cursor.fetchone()
        total_bytes = int(db_metrics["total_bytes"]) if db_metrics and db_metrics["total_bytes"] is not None else 0
        total_tables = db_metrics["total_tables"] if db_metrics else 0
        
        total_gb = float(total_bytes) / (1024 * 1024 * 1024)
        
        # Check for large tables (> 50 GB or > 10M rows)
        cursor.execute(f"""
            SELECT TABLE_NAME, TABLE_ROWS, (DATA_LENGTH + INDEX_LENGTH) as size_bytes
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_SCHEMA = '{database}' 
              AND TABLE_TYPE = 'BASE TABLE'
              AND (DATA_LENGTH + INDEX_LENGTH > 53687091200 OR TABLE_ROWS > 10000000)
            ORDER BY size_bytes DESC;
        """)
        large_tables = cursor.fetchall()
        
        size_status = "PASS"
        size_msg = f"Database size is {total_gb:.2f} GB with {total_tables} tables."
        if large_tables:
            size_status = "WARNING"
            size_msg += f" Found {len(large_tables)} large table(s) (>50GB or >10M rows)."
            
        add_check(
            category="Scale & Capacity",
            name="Database Size & Scale Check",
            status=size_status,
            message=size_msg,
            details={
                "total_bytes": total_bytes,
                "total_gb": total_gb,
                "total_tables": total_tables,
                "large_tables": [
                    {
                        "table_name": row["TABLE_NAME"],
                        "rows": row["TABLE_ROWS"],
                        "size_gb": float(row["size_bytes"]) / (1024 * 1024 * 1024)
                    }
                    for row in large_tables
                ]
            },
            remediation="Verify target instance disk size and IOPS can handle the load. Large tables may require splitting, partition-based loading, or migrating during off-peak hours."
        )

        # 9. Source Database Load & Lock Risk Check
        lock_waits = 0
        try:
            cursor.execute("SELECT COUNT(*) as lock_waits FROM INFORMATION_SCHEMA.INNODB_TRX WHERE trx_state = 'LOCK WAIT';")
            lock_row = cursor.fetchone()
            lock_waits = lock_row["lock_waits"] if lock_row else 0
        except Exception:
            pass
            
        threads_connected = int(all_vars.get("Threads_connected", 0))
        max_connections = int(all_vars.get("max_connections", 151))
        conn_utilization = (threads_connected / max_connections) * 100 if max_connections > 0 else 0
        
        load_status = "PASS"
        load_msg = f"Database active load is stable ({threads_connected} active connections, {lock_waits} active lock waits)."
        load_remediation = ""
        
        if lock_waits > 0:
            load_status = "WARNING"
            load_msg = f"Detected {lock_waits} active transaction lock wait(s) in InnoDB."
            load_remediation = "Warning: Active transaction lock waits are present. Starting a migration snapshot might increase lock contention. It is recommended to resolve lock waits or run migration during off-peak hours."
        elif conn_utilization > 80:
            load_status = "WARNING"
            load_msg = f"High connection utilization: {threads_connected} active / {max_connections} max connections ({conn_utilization:.1f}%)."
            load_remediation = "Warning: High connection usage on source. Ensure client traffic is throttled or schedule the migration snapshot during a low-traffic window."

        add_check(
            category="Source Database Health",
            name="Active Database Load & Lock Check",
            status=load_status,
            message=load_msg,
            details={
                "threads_connected": threads_connected,
                "max_connections": max_connections,
                "connection_utilization_pct": conn_utilization,
                "active_lock_waits": lock_waits
            },
            remediation=load_remediation
        )

        # 10. Optimal Target Instance Sizer (MySQL)
        target_sizer_status = "INFO"
        
        # Sizing recommendations logic
        if total_gb < 50:
            rec_instance = "db-custom-2-7680 (2 vCPU, 7.5 GB RAM)"
            rec_disk = "50 GB (SSD)"
        elif total_gb < 200:
            rec_instance = "db-custom-4-15360 (4 vCPU, 15 GB RAM)"
            rec_disk = "200 GB (SSD)"
        elif total_gb < 1000:
            rec_instance = "db-custom-8-30720 (8 vCPU, 30 GB RAM)"
            rec_disk = "1000 GB (SSD, High-Performance)"
        else:
            rec_instance = "db-custom-16-61440 (16 vCPU, 60 GB RAM)"
            rec_disk = f"{int(total_gb * 1.2)} GB (SSD, High-Performance)"
            
        # Adjust for connections
        if max_connections > 1000:
            rec_instance += " - Recommended Memory scale-up for high connections."

        sizer_msg = f"Recommended Target Database Sizing: Instance: {rec_instance}, Disk: {rec_disk}."
        
        add_check(
            category="Scale & Capacity",
            name="Optimal Target Instance Sizing",
            status=target_sizer_status,
            message=sizer_msg,
            details={
                "source_database_size_gb": total_gb,
                "source_max_connections": max_connections,
                "recommended_target_instance": rec_instance,
                "recommended_target_disk": rec_disk
            },
            remediation="Provision target database instance with the recommended parameters or higher to prevent CPU/IOPS bottlenecks during logical replication."
        )

        conn.close()
    except Exception as e:
        report["overall_status"] = "FAIL"
        report["errors"].append(f"Diagnostics error: {str(e)}")
        add_check(
            category="Diagnostics Check",
            name="Run Diagnostics Query",
            status="FAIL",
            message=f"Failed to execute diagnostic queries.",
            details=str(e),
            remediation="Verify that the migration user has SELECT access to INFORMATION_SCHEMA and SHOW GLOBAL VARIABLES permission."
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
