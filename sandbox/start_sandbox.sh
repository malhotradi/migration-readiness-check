#!/bin/bash
set -e

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "===================================================="
echo "🚀 Starting Mock Database Sandbox environment..."
echo "===================================================="

# Clean up any existing sandbox containers
echo "Stopping and removing any old sandbox containers..."
docker rm -f mysql-source postgres-source 2>/dev/null || true

# Start MySQL Container
echo "Starting MySQL Source container..."
docker run --name mysql-source \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=billing_db \
  -v "$DIR/setup_mysql_mock.sql:/docker-entrypoint-initdb.d/setup_mysql_mock.sql" \
  -d mysql:8.0 --binlog-format=STATEMENT --gtid-mode=OFF --enforce-gtid-consistency=OFF

# Start PostgreSQL Container
echo "Starting PostgreSQL Source container..."
docker run --name postgres-source \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=rootpassword \
  -e POSTGRES_DB=customer_db \
  -v "$DIR/setup_postgres_mock.sql:/docker-entrypoint-initdb.d/setup_postgres_mock.sql" \
  -d postgres:14 postgres -c wal_level=replica -c max_wal_senders=0

echo ""
echo "🕒 Waiting for databases to initialize..."
echo "===================================================="

# Helper function to check MySQL readiness
wait_for_mysql() {
  echo "Checking MySQL container..."
  until docker exec mysql-source mysqladmin ping -uroot -prootpassword --silent &>/dev/null; do
    echo "  - MySQL is starting up... waiting..."
    sleep 3
  done
  echo "✅ MySQL is ready and seeded!"
}

# Helper function to check Postgres readiness
wait_for_postgres() {
  echo "Checking PostgreSQL container..."
  until docker exec postgres-source pg_isready -U postgres &>/dev/null; do
    echo "  - PostgreSQL is starting up... waiting..."
    sleep 3
  done
  echo "✅ PostgreSQL is ready and seeded!"
}

wait_for_mysql
wait_for_postgres

echo ""
echo "===================================================="
echo "🎉 Mock Databases are fully running and seeded!"
echo "===================================================="
echo "You can now connect to them with these credentials:"
echo ""
echo "1. MySQL Source:"
echo "   - Host: 127.0.0.1"
echo "   - Port: 3306"
echo "   - Username: migration_user"
echo "   - Password: migpass"
echo "   - Database: billing_db"
echo ""
echo "2. PostgreSQL Source:"
echo "   - Host: 127.0.0.1"
echo "   - Port: 5432"
echo "   - Username: migration_user"
echo "   - Password: migpass"
echo "   - Database: customer_db"
echo "===================================================="
