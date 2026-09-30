-- Khởi tạo schema cơ sở dữ liệu hệ thống Training Management

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    failed_login_attempts INT NOT NULL DEFAULT 0,
    locked_until DATETIME NULL DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    refresh_jti VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    last_activity_at DATETIME NOT NULL,
    idle_expires_at DATETIME NOT NULL,
    absolute_expires_at DATETIME NOT NULL,
    revoked_at DATETIME NULL DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
