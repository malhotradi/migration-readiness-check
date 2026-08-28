# Database Migration Readiness Checker Agent

This directory contains a fresh ADK (Agent Development Kit) agent designed to perform pre-migration database checks for **MySQL, PostgreSQL, SQL Server, and Oracle** databases migrating from various environments (AWS, Azure, On-premise) to GCP (Cloud SQL or AlloyDB).

## Structure
- `agents/`
  - `tools/`
    - `mysql_checks.py`: Source MySQL diagnostics (binlogs, engines, primary keys, privileges, definers, database size).
    - `gcp_checks.py`: Target Cloud SQL instance diagnostics (disk capacity, auto-resize, VPC peering, flags, version compatibility).
  - `schemas.py`: Input/Output Pydantic structures for the agent.
  - `prompt.py`: Detailed instruction guidelines for the agent.
  - `agent.py`: Initialized ADK Agent instance.
- `main.py`: Serving script to spin up the agent in a FastAPI application with the ADK Web UI.
- `test_locally.py`: CLI tool to execute the playbook generation agent directly from your terminal.

---

## Prerequisites
Ensure the virtual environment is active.
```bash
source venv/bin/activate
```

---

## How to Test Locally (CLI)

The script `test_locally.py` supports two modes of execution and multiple database engines (MySQL, PostgreSQL, SQL Server):

### 1. Playbook Generation Mode (Static Manual Instructions)
Generate a sequential manual checklist of SQL queries and commands to run, without requiring database or Cloud credentials. This is supported for **MySQL, PostgreSQL, and SQL Server**:

* **MySQL Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode playbook \
    --source-engine "MySQL" \
    --target-engine "Cloud SQL for MySQL" \
    --provider "aws" \
    --database "DB_NAME" \
    --migration-user "MIGRATION_USER" \
    --output "playbook_mysql.md"
  ```

* **PostgreSQL Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode playbook \
    --source-engine "PostgreSQL" \
    --target-engine "Cloud SQL for PostgreSQL" \
    --provider "aws" \
    --database "DB_NAME" \
    --migration-user "MIGRATION_USER" \
    --output "playbook_postgres.md"
  ```

* **Oracle Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode playbook \
    --source-engine "Oracle" \
    --target-engine "Cloud SQL for PostgreSQL" \
    --provider "onprem" \
    --database "ORCL_SID" \
    --migration-user "MIGRATION_USER" \
    --output "playbook_oracle.md"
  ```

### 2. Live Diagnostics Mode (Automated Queries)
Execute live database queries and GCP API checks directly using connection details, compiling an automated diagnostics report. This is supported for **MySQL, PostgreSQL, SQL Server, and Oracle**:

* **MySQL Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode diagnostics \
    --source-engine "MySQL" \
    --provider "aws" \
    --database "DB_NAME" \
    --host "SOURCE_HOST" \
    --user "SOURCE_DB_USER" \
    --password "SOURCE_DB_PASSWORD" \
    --port 3306 \
    --target-gcp-project "TARGET_GCP_PROJECT" \
    --target-gcp-instance "TARGET_SQL_INSTANCE" \
    --output "diagnostics_mysql.md"
  ```

* **PostgreSQL Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode diagnostics \
    --source-engine "PostgreSQL" \
    --target-engine "Cloud SQL for PostgreSQL" \
    --provider "aws" \
    --database "DB_NAME" \
    --host "SOURCE_HOST" \
    --user "SOURCE_DB_USER" \
    --password "SOURCE_DB_PASSWORD" \
    --port 5432 \
    --target-gcp-project "TARGET_GCP_PROJECT" \
    --target-gcp-instance "TARGET_SQL_INSTANCE" \
    --output "diagnostics_postgres.md"
  ```

* **Oracle Example:**
  ```bash
  ./venv/bin/python MigrationReadinessCheck/test_locally.py \
    --mode diagnostics \
    --source-engine "Oracle" \
    --target-engine "Cloud SQL for PostgreSQL" \
    --provider "onprem" \
    --database "ORCL_SERVICE_NAME" \
    --host "SOURCE_HOST" \
    --user "SOURCE_DB_USER" \
    --password "SOURCE_DB_PASSWORD" \
    --port 1521 \
    --target-gcp-project "TARGET_GCP_PROJECT" \
    --target-gcp-instance "TARGET_SQL_INSTANCE" \
    --output "diagnostics_oracle.md"
  ```

### 3. Playbook Evaluation Mode (Human-in-the-Loop)
If direct database connection is blocked (e.g. by security policies or firewalls), you can use the Excel/Google Sheets workflow:

1. Generate the playbook in `playbook` mode (this creates both a `.md` file and a `.csv` file).
2. Open the `.csv` file in Excel or Google Sheets.
3. Run the SQL queries manually on your database.
4. Fill in the **Actual Output** and **Status** columns in your spreadsheet.
5. Export/save it back as a CSV file.
6. Feed the completed CSV back to the agent in `evaluate` mode to generate a final **Readiness Certification Report**:

```bash
./venv/bin/python MigrationReadinessCheck/test_locally.py \
  --mode evaluate \
  --source-engine "MySQL" \
  --provider "aws" \
  --database "my_db" \
  --completed-csv "path/to/my_completed_playbook.csv" \
  --output "readiness_assessment"
```
This generates `readiness_assessment.md` (the readable report showing PASSED and FAILED checks with detailed remediations) and `readiness_assessment.csv` (the updated structured spreadsheet).

## Quick Test Sandbox (Mock Databases)

To quickly test live diagnostics and auto-remediations, a pre-configured Docker Compose environment is provided under the `sandbox/` directory. It spins up MySQL and PostgreSQL databases pre-seeded with tables, but purposefully misconfigured to trigger agent diagnostics.

1. **Start the Sandbox**:
   ```bash
   ./MigrationReadinessCheck/sandbox/start_sandbox.sh
   ```
2. **Connection Parameters for Test**:
   * **MySQL Source**: Host `127.0.0.1`, Port `3306`, User `migration_user`, Password `migpass`, DB `billing_db`.
   * **PostgreSQL Source**: Host `127.0.0.1`, Port `5432`, User `migration_user`, Password `migpass`, DB `customer_db`.

---

## How to Run the ADK Agent (Web UI)

To launch the web interface of the Migration Readiness Checker Agent:

1. **Start the FastAPI App**:
   ```bash
   ./venv/bin/python MigrationReadinessCheck/main.py
   ```
2. **Access the UI**:
   Open your browser and navigate to `http://localhost:8080` (or the port outputted in the terminal logs).
3. **Interact**:
   Select the source and target engines, enter the details (and optionally connection credentials for MySQL automated diagnostics) in the schema input fields, and the agent will run validation checks, compile logs, and generate a beautiful interactive markdown migration readiness report or playbook.
