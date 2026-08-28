-- Create migration test user with limited privileges
CREATE USER IF NOT EXISTS 'migration_user'@'%' IDENTIFIED BY 'migpass';
GRANT SELECT ON billing_db.* TO 'migration_user'@'%';
FLUSH PRIVILEGES;

-- Create sample tables
USE billing_db;

CREATE TABLE IF NOT EXISTS transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- This table has no primary key to trigger agent warnings
CREATE TABLE IF NOT EXISTS transaction_logs (
    log_id INT,
    message VARCHAR(255),
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- This table uses MyISAM engine (non-InnoDB) to trigger engine warnings
CREATE TABLE IF NOT EXISTS archive_records (
    record_id INT PRIMARY KEY,
    data TEXT
) ENGINE=MyISAM;
