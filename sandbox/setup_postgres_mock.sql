-- Create pg migration user
CREATE USER migration_user WITH PASSWORD 'migpass';
GRANT USAGE ON SCHEMA public TO migration_user;

-- Create sample tables
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- This table has no primary key to trigger agent warnings
CREATE TABLE IF NOT EXISTS transaction_logs (
    log_id INT,
    action_type VARCHAR(50),
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

GRANT SELECT ON ALL TABLES IN SCHEMA public TO migration_user;
