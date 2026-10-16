-- Migration / Seed: 032_add_schedule_rbac_permissions.sql
-- Định nghĩa quyền chuyên biệt cho phân hệ Thời khóa biểu và Lịch cá nhân (SCRUM-228 & RBAC)
-- Tách biệt hoàn toàn khỏi course.view / course.manage

-- 1. Bổ sung các Permissions cho Lịch
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-schedule-view', 'schedule.view', 'Xem thời khóa biểu', 'Xem thời khóa biểu và lịch giảng dạy/học tập toàn trường', NOW(), NOW()),
    ('perm-id-schedule-manage', 'schedule.manage', 'Quản lý thời khóa biểu', 'Tạo, sửa, hủy và điều chỉnh lịch học, thời khóa biểu', NOW(), NOW()),
    ('perm-id-schedule-personal-view', 'schedule.personal_view', 'Xem lịch cá nhân', 'Xem thời khóa biểu cá nhân của học viên hoặc lịch giảng dạy của giảng viên', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- 2. Gán Role - Permissions
-- Quản trị viên (admin): xem và quản lý thời khóa biểu toàn trường
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-admin', 'perm-id-schedule-view', NOW()),
    ('role-id-admin', 'perm-id-schedule-manage', NOW());

-- Quản lý đào tạo (training_manager): xem và quản lý thời khóa biểu toàn trường
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-training-manager', 'perm-id-schedule-view', NOW()),
    ('role-id-training-manager', 'perm-id-schedule-manage', NOW());

-- Giảng viên (trainer): xem thời khóa biểu chung và xem lịch giảng dạy cá nhân
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainer', 'perm-id-schedule-view', NOW()),
    ('role-id-trainer', 'perm-id-schedule-personal-view', NOW());

-- Học viên (trainee): chỉ xem lịch học cá nhân của mình
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainee', 'perm-id-schedule-personal-view', NOW());
