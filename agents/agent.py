import os
from google.adk.agents import Agent
from .prompt import PLAYBOOK_GENERATION_PROMPT
from .schemas import PlaybookInput, MigrationReadinessPlaybook
from .tools.mysql_checks import check_mysql_readiness
from .tools.postgres_checks import check_postgres_readiness
from .tools.sqlserver_checks import check_sqlserver_readiness
from .tools.oracle_checks import check_oracle_readiness
from .tools.gcp_checks import check_gcp_target_readiness
from .tools.web_reader import fetch_latest_gcp_migration_rules

root_agent = Agent(
    name="migration_readiness_agent",
    model="gemini-2.5-pro",
    instruction=PLAYBOOK_GENERATION_PROMPT,
    tools=[
        check_mysql_readiness, 
        check_postgres_readiness, 
        check_sqlserver_readiness, 
        check_oracle_readiness,
        check_gcp_target_readiness,
        fetch_latest_gcp_migration_rules
    ],
    input_schema=PlaybookInput,
    output_schema=MigrationReadinessPlaybook,
    output_key="migration_readiness_playbook"
)
