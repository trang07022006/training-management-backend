-- Migration 028: Tạo bảng classrooms phục vụ SCRUM-221 (Quản lý phòng học vật lý và trực tuyến)
CREATE TABLE IF NOT EXISTS classrooms (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    room_code VARCHAR(50) NOT NULL UNIQUE,
    room_name VARCHAR(100) NOT NULL,
    room_type VARCHAR(20) NOT NULL DEFAULT 'physical', -- 'physical' hoặc 'online'
    capacity INT NULL,                                 -- Sức chứa phòng vật lý (> 0), phòng online để NULL
    online_link TEXT NULL,                             -- Đường dẫn phòng trực tuyến, phòng vật lý để NULL
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_classrooms_type (room_type),
    INDEX idx_classrooms_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
