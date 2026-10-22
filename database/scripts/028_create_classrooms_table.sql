-- Migration 028: Tạo bảng classrooms và khởi tạo danh mục phòng học mẫu (SCRUM-221)
-- Quản lý phòng học vật lý và liên kết phòng học trực tuyến

CREATE TABLE IF NOT EXISTS classrooms (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    room_code VARCHAR(50) NOT NULL UNIQUE,
    room_name VARCHAR(255) NOT NULL,
    room_type VARCHAR(50) NOT NULL DEFAULT 'physical',
    capacity INT NULL,
    online_link VARCHAR(500) NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    INDEX idx_classrooms_room_type (room_type),
    INDEX idx_classrooms_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Khởi tạo danh mục phòng học mẫu
INSERT IGNORE INTO classrooms (id, room_code, room_name, room_type, capacity, online_link, status, created_at, updated_at)
VALUES
    ('room-id-p101', 'P101', 'Phòng học 101 - Nhà A', 'physical', 40, NULL, 'active', NOW(), NOW()),
    ('room-id-p102', 'P102', 'Phòng học 102 - Nhà A', 'physical', 45, NULL, 'active', NOW(), NOW()),
    ('room-id-p201', 'P201', 'Phòng học 201 - Nhà B', 'physical', 50, NULL, 'active', NOW(), NOW()),
    ('room-id-lab01', 'LAB-01', 'Phòng Thực hành Máy tính 01', 'physical', 35, NULL, 'active', NOW(), NOW()),
    ('room-id-lab02', 'LAB-02', 'Phòng Thực hành Máy tính 02', 'physical', 35, NULL, 'active', NOW(), NOW()),
    ('room-id-online-zoom', 'ONL-ZOOM-01', 'Phòng học Trực tuyến Zoom 01', 'online', NULL, 'https://zoom.us/j/ictu-room-01', 'active', NOW(), NOW()),
    ('room-id-online-meet', 'ONL-MEET-01', 'Phòng học Trực tuyến Google Meet', 'online', NULL, 'https://meet.google.com/ictu-class-01', 'active', NOW(), NOW());
