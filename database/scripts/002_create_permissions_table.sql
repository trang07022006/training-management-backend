-- Migration: 002_create_permissions_table.sql
-- Bảng permissions quản lý các quyền hạn độc lập trong hệ thống RBAC (SCRUM-61)

CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    code VARCHAR(100) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    description VARCHAR(255) NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_permissions_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
