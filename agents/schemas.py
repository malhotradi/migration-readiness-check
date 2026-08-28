from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class PlaybookInput(BaseModel):
    """Input parameters for generating the Migration Readiness Playbook or running/evaluating diagnostics."""
    execution_mode: Literal["Generate Playbook Only", "Run Automated Diagnostics", "Evaluate Playbook"] = Field(
        "Generate Playbook Only",
        description="Choose whether to only generate the static playbook, run automated diagnostics, or evaluate user-submitted CSV results."
    )
    auto_remediate: bool = Field(
        False,
        description="If True, the agent will attempt to execute remediation commands automatically on the source database/GCP target when a check fails."
    )
    source_engine: Literal["MySQL", "PostgreSQL", "SQL Server", "Oracle"] = Field(
        "MySQL",
        description="The engine type of the source database."
    )
    target_engine: Literal["Cloud SQL for MySQL", "Cloud SQL for PostgreSQL", "Cloud SQL for SQL Server", "AlloyDB"] = Field(
        "Cloud SQL for MySQL",
        description="The engine type of the target GCP database."
    )
    source_provider: Literal["AWS RDS/Aurora", "Azure Database", "On-premise/Self-hosted"] = Field(
        "On-premise/Self-hosted",
        description="The provider hosting the source database."
    )
    source_mysql_version: Optional[str] = Field(
        "8.0",
        description="The major version of the source database if it is MySQL (e.g. 5.7, 8.0)."
    )
    source_postgres_version: Optional[str] = Field(
        "14",
        description="The major version of the source database if it is PostgreSQL (e.g. 12, 13, 14, 15)."
    )
    source_sqlserver_version: Optional[str] = Field(
        "2019",
        description="The major version of the source database if it is SQL Server (e.g. 2016, 2017, 2019)."
    )
    source_oracle_version: Optional[str] = Field(
        "19c",
        description="The major version of the source database if it is Oracle (e.g. 11g, 12c, 19c, 21c)."
    )
    target_version: str = Field(
        "8.0",
        description="The major version of the target GCP database (e.g. 8.0, 14, 2019, 19c)."
    )
    database_name: str = Field(
        description="The name of the database/schema to migrate."
    )
    migration_user: str = Field(
        "migration_user",
        description="The username to be created and used for the migration."
    )
    migration_type: Literal["Online CDC", "Offline/One-time Dump"] = Field(
        "Online CDC",
        description="The migration strategy: Online CDC (using replication) or Offline/One-time Dump."
    )
    # Optional connection parameters for "Run Automated Diagnostics" mode
    source_host: Optional[str] = Field(
        None,
        description="The host IP or domain of the source database. Required for automated diagnostics."
    )
    source_port: Optional[int] = Field(
        None,
        description="The port of the source database."
    )
    source_password: Optional[str] = Field(
        None,
        description="The password for the migration user on the source database. Required for automated diagnostics."
    )
    target_gcp_project: Optional[str] = Field(
        None,
        description="The GCP Project ID containing the target instance. Required for automated diagnostics."
    )
    target_gcp_instance: Optional[str] = Field(
        None,
        description="The instance ID of the target GCP database. Required for automated diagnostics."
    )
    # Input field for "Evaluate Playbook" mode (parsed CSV steps)
    completed_steps: Optional[List['PlaybookStep']] = Field(
        None,
        description="The list of completed playbook steps (including user-submitted actual outputs and statuses) to evaluate."
    )

class PlaybookStep(BaseModel):
    """A single sequential validation step to run on either the source or target database."""
    step_number: int = Field(description="Sequential step number.")
    category: str = Field(description="Category of check (e.g. Connectivity, Logging, Schema, Permissions).")
    title: str = Field(description="Brief title of the verification step.")
    description: str = Field(description="Detailed explanation of what is checked and why.")
    command_to_run: str = Field(description="The exact SQL query or terminal command to execute.")
    expected_output: str = Field(description="The expected value or output patterns to verify success.")
    actual_output: Optional[str] = Field(
        None, 
        description="The actual output returned by the live diagnostic run or entered by the user."
    )
    status: Literal["PASS", "FAIL", "WARNING", "INFO", "NOT_RUN"] = Field(
        "NOT_RUN",
        description="The status of this step: PASS, FAIL, WARNING, INFO, or NOT_RUN."
    )
    remediation: str = Field(description="The SQL query, terminal command, or configuration steps to run to fix the issue if the check fails.")

class MigrationReadinessPlaybook(BaseModel):
    """Output structure containing sequential readiness checklists/reports for source and target environments."""
    source_provider: str = Field(description="The source database cloud or environment provider.")
    migration_type: str = Field(description="The chosen migration strategy (CDC or offline).")
    playbook_summary: str = Field(description="High-level summary of the verification plan or diagnostics results.")
    source_steps: List[PlaybookStep] = Field(
        description="Sequential steps/check results for the source database."
    )
    target_steps: List[PlaybookStep] = Field(
        description="Sequential steps/check results for the target GCP environment."
    )
    markdown_playbook: str = Field(
        description="A beautiful, comprehensive markdown report/playbook ready to be saved as an artifact or shared."
    )
    csv_playbook: str = Field(
        description="A RFC 4180-compliant CSV string containing all steps, ready to be saved as a .csv file and opened in Excel or Google Sheets."
    )
