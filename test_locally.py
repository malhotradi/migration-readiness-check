import sys
import os
import json
import csv
import argparse
import asyncio
from dotenv import load_dotenv

# Ensure the parent directory is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.agent import root_agent
from google.adk.apps.app import App
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.genai import types

def map_provider(p: str) -> str:
    p_lower = p.lower()
    if "aws" in p_lower or "aurora" in p_lower:
        return "AWS RDS/Aurora"
    if "azure" in p_lower:
        return "Azure Database"
    return "On-premise/Self-hosted"

def map_source_engine(e: str) -> str:
    e_lower = e.lower()
    if "postgres" in e_lower:
        return "PostgreSQL"
    if "sqlserver" in e_lower or "sql-server" in e_lower or "mssql" in e_lower:
        return "SQL Server"
    if "oracle" in e_lower:
        return "Oracle"
    return "MySQL"

def map_target_engine(e: str) -> str:
    e_lower = e.lower()
    if "postgres" in e_lower:
        return "Cloud SQL for PostgreSQL"
    if "sqlserver" in e_lower or "sql-server" in e_lower or "mssql" in e_lower:
        return "Cloud SQL for SQL Server"
    if "alloydb" in e_lower:
        return "AlloyDB"
    return "Cloud SQL for MySQL"

async def run_agent_locally(input_data: dict) -> dict:
    # Load environment variables from the agent's .env file
    agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
    load_dotenv(os.path.join(agents_dir, ".env"))
    
    # Dynamically clear tools if not running automated diagnostics
    if input_data.get("execution_mode") in ["Generate Playbook Only", "Evaluate Playbook"]:
        root_agent.tools = []
        
    app = App(name="migration_readiness_agent", root_agent=root_agent)
    session_service = InMemorySessionService()
    artifact_service = InMemoryArtifactService()
    runner = Runner(app=app, session_service=session_service, artifact_service=artifact_service)
    
    session = await session_service.create_session(
        app_name=app.name,
        user_id="local_user"
    )
    
    query_json = json.dumps(input_data)
    new_message = types.Content(role='user', parts=[types.Part(text=query_json)])
    
    print(f"Running agent for {input_data['source_engine']} -> {input_data['target_engine']} in mode '{input_data['execution_mode']}'...")
    playbook = None
    accumulated_text = ""
    
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=new_message
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    accumulated_text += part.text
                    print(part.text, end="", flush=True)
        if event.output:
            playbook = event.output
            
    print("\n")
    
    # Fallback parsing in case ADK schema validator fails to yield event.output
    if playbook is None and accumulated_text.strip():
        try:
            clean_text = accumulated_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            elif clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
            
            playbook = json.loads(clean_text)
        except Exception:
            pass
            
    return playbook

def parse_completed_csv(file_path: str) -> list:
    """Parses the user-completed CSV playbook file and returns a list of step dictionaries."""
    completed_steps = []
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Completed CSV file not found at: {file_path}")
        
    with open(file_path, mode='r', encoding='utf-8') as f:
        # Standard RFC 4180 parsing
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            # Strip whitespace from keys and values
            row = {k.strip(): v.strip() if v else "" for k, v in row.items()}
            
            # Require minimum keys
            required_keys = ["Step Number", "Category", "Title", "Command to Run", "Expected Output", "Remediation"]
            missing_keys = [k for k in required_keys if k not in row]
            if missing_keys:
                raise ValueError(f"CSV is missing required columns: {missing_keys} (Row {idx+1})")
                
            step_number = int(row["Step Number"])
            category = row["Category"]
            title = row["Title"]
            description = row.get("Description", "")
            command_to_run = row["Command to Run"]
            expected_output = row["Expected Output"]
            actual_output = row.get("Actual Output")
            status = row.get("Status", "NOT_RUN")
            remediation = row["Remediation"]
            
            step = {
                "step_number": step_number,
                "category": category,
                "title": title,
                "description": description,
                "command_to_run": command_to_run,
                "expected_output": expected_output,
                "actual_output": actual_output if actual_output else None,
                "status": status if status else "NOT_RUN",
                "remediation": remediation
            }
            completed_steps.append(step)
            
    return completed_steps

def main():
    parser = argparse.ArgumentParser(description="Generate database migration readiness playbook, run live diagnostics, or evaluate user CSV results.")
    
    # Execution Mode
    parser.add_argument("--mode", default="playbook", choices=["playbook", "diagnostics", "evaluate"],
                        help="Execution mode: 'playbook' (generate manual check files), 'diagnostics' (runs live automated database queries), or 'evaluate' (evaluates a user-completed CSV). (default: playbook)")
    
    # Database Engines
    parser.add_argument("--source-engine", default="MySQL",
                        choices=["MySQL", "PostgreSQL", "SQL Server", "Oracle", "mysql", "postgres", "sqlserver", "mssql", "oracle"],
                        help="Source database engine type (default: MySQL)")
    parser.add_argument("--target-engine", default="Cloud SQL for MySQL",
                        choices=["Cloud SQL for MySQL", "Cloud SQL for PostgreSQL", "Cloud SQL for SQL Server", "AlloyDB", "mysql", "postgres", "sqlserver", "alloydb"],
                        help="Target database engine type (default: Cloud SQL for MySQL)")

    # Input parameters
    parser.add_argument("--provider", required=True, 
                        choices=["AWS RDS/Aurora", "Azure Database", "On-premise/Self-hosted", "aws", "azure", "onprem"],
                        help="Source database cloud or environment provider")
    parser.add_argument("--source-mysql-version", default="8.0", help="Major version of source MySQL if applicable (default: 8.0)")
    parser.add_argument("--source-postgres-version", default="14", help="Major version of source PostgreSQL if applicable (default: 14)")
    parser.add_argument("--source-sqlserver-version", default="2019", help="Major version of source SQL Server if applicable (default: 2019)")
    parser.add_argument("--source-oracle-version", default="19c", help="Major version of source Oracle if applicable (default: 19c)")
    parser.add_argument("--target-version", default="8.0", help="Major version of the target database (e.g. 8.0, 14, 2019, 19c) (default: 8.0)")
    parser.add_argument("--database", required=True, help="Database name to migrate")
    parser.add_argument("--migration-user", default="migration_user", help="User to create/use for migration (default: migration_user)")
    parser.add_argument("--migration-type", default="Online CDC", choices=["Online CDC", "Offline/One-time Dump", "cdc", "offline"],
                        help="Migration strategy/type (default: Online CDC)")
    
    # Connection parameters for diagnostics mode
    parser.add_argument("--host", help="Source host IP/domain. Required for 'diagnostics' mode.")
    parser.add_argument("--user", help="Source database user. Required for 'diagnostics' mode.")
    parser.add_argument("--password", help="Source database password. Required for 'diagnostics' mode.")
    parser.add_argument("--port", type=int, help="Source database port.")
    parser.add_argument("--target-gcp-project", help="Target GCP Project ID. Required for target checks in 'diagnostics' mode.")
    parser.add_argument("--target-gcp-instance", help="Target Cloud SQL Instance ID. Required for target checks in 'diagnostics' mode.")
    
    # Input parameter for evaluate mode
    parser.add_argument("--completed-csv", help="Path to the user-filled CSV playbook/checklist file. Required when --mode is 'evaluate'.")
    
    # Active auto-remediate parameter
    parser.add_argument("--auto-remediate", action="store_true", default=False,
                        help="If set, the agent will attempt to automatically run SQL statements/commands to fix failures when in 'diagnostics' mode. (default: False)")
    
    # Output parameter
    parser.add_argument("--output", help="Base file name/path to save the generated report or playbook (without extension). E.g. --output my_report will write my_report.md and my_report.csv.")

    args = parser.parse_args()

    # Map engine arguments
    source_engine = map_source_engine(args.source_engine)
    target_engine = map_target_engine(args.target_engine)

    completed_steps = None

    # Determine execution mode and default outputs
    if args.mode == "diagnostics":
        execution_mode = "Run Automated Diagnostics"
        default_output = "migration_diagnostics_report"
        if not args.host or not args.user or not args.password:
            parser.error("--host, --user, and --password are required when --mode is 'diagnostics'.")
    elif args.mode == "evaluate":
        execution_mode = "Evaluate Playbook"
        default_output = "migration_readiness_assessment"
        if not args.completed_csv:
            parser.error("--completed-csv is required when --mode is 'evaluate'.")
        try:
            completed_steps = parse_completed_csv(args.completed_csv)
        except Exception as e:
            print(f"Error parsing completed CSV file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        execution_mode = "Generate Playbook Only"
        default_output = "migration_readiness_playbook"

    base_output = args.output or default_output
    md_output_file = f"{base_output}.md"
    csv_output_file = f"{base_output}.csv"

    # Map provider
    provider = map_provider(args.provider)
    
    migration_type = args.migration_type
    if migration_type.lower() == "cdc":
        migration_type = "Online CDC"
    elif migration_type.lower() == "offline":
        migration_type = "Offline/One-time Dump"
        
    input_data = {
        "execution_mode": execution_mode,
        "auto_remediate": args.auto_remediate,
        "source_engine": source_engine,
        "target_engine": target_engine,
        "source_provider": provider,
        "source_mysql_version": args.source_mysql_version,
        "source_postgres_version": args.source_postgres_version,
        "source_sqlserver_version": args.source_sqlserver_version,
        "source_oracle_version": args.source_oracle_version,
        "target_version": args.target_version,
        "database_name": args.database,
        "migration_user": args.migration_user,
        "migration_type": migration_type,
        "source_host": args.host,
        "source_port": args.port,
        "source_password": args.password,
        "target_gcp_project": args.target_gcp_project,
        "target_gcp_instance": args.target_gcp_instance,
        "completed_steps": completed_steps
    }

    # Filter out None values so they default to schema defaults
    input_data = {k: v for k, v in input_data.items() if v is not None}

    try:
        playbook = asyncio.run(run_agent_locally(input_data))
    except Exception as e:
        print(f"Failed to execute agent: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract markdown and CSV outputs
    markdown_content = None
    csv_content = None
    
    if playbook:
        if hasattr(playbook, "markdown_playbook"):
            markdown_content = playbook.markdown_playbook
        elif isinstance(playbook, dict) and "markdown_playbook" in playbook:
            markdown_content = playbook["markdown_playbook"]
            
        if hasattr(playbook, "csv_playbook"):
            csv_content = playbook.csv_playbook
        elif isinstance(playbook, dict) and "csv_playbook" in playbook:
            csv_content = playbook["csv_playbook"]

    # Write files
    if markdown_content:
        try:
            with open(md_output_file, "w", encoding="utf-8") as f:
                f.write(markdown_content)
            print(f"Success! Markdown report/playbook saved to: {os.path.abspath(md_output_file)}")
        except Exception as e:
            print(f"Failed to save markdown report: {e}", file=sys.stderr)
            
    if csv_content:
        try:
            with open(csv_output_file, "w", encoding="utf-8") as f:
                f.write(csv_content)
            print(f"Success! CSV checklist saved to: {os.path.abspath(csv_output_file)}")
        except Exception as e:
            print(f"Failed to save CSV checklist: {e}", file=sys.stderr)

    if not markdown_content and not csv_content:
        print("Error: Agent run succeeded but output did not contain valid report strings.", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
