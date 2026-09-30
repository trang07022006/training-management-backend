-- Migration / Seed: 005_seed_rbac_initial_data.sql
-- Khởi tạo dữ liệu nền idempotent cho Role, Permission và Role_Permissions (SCRUM-64)
-- Chạy nhiều lần không gây lỗi trùng lặp và không xóa dữ liệu người dùng hiện có.

-- 1. Khởi tạo Roles chuẩn
INSERT INTO roles (id, code, name, description, created_at, updated_at)
VALUES 
    ('role-id-admin', 'admin', 'Quản trị viên', 'Toàn quyền quản trị hệ thống và người dùng', NOW(), NOW()),
    ('role-id-trainer', 'trainer', 'Giảng viên', 'Quản lý khóa đào tạo, học viên và điểm danh', NOW(), NOW()),
    ('role-id-trainee', 'trainee', 'Học viên', 'Tham gia các khóa đào tạo và theo dõi tiến độ', NOW(), NOW()),
    ('role-id-user', 'user', 'Người dùng', 'Người dùng thông thường trong hệ thống', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- 2. Khởi tạo Permissions chuẩn
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-user-view', 'user.view', 'Xem người dùng', 'Xem danh sách và thông tin tài khoản người dùng', NOW(), NOW()),
    ('perm-id-user-manage', 'user.manage', 'Quản trị người dùng', 'Thêm, sửa, khóa hoặc phân quyền người dùng', NOW(), NOW()),
    ('perm-id-course-view', 'course.view', 'Xem khóa học', 'Xem chương trình và nội dung đào tạo', NOW(), NOW()),
    ('perm-id-course-manage', 'course.manage', 'Quản trị khóa học', 'Tạo, sửa và cập nhật tài liệu đào tạo', NOW(), NOW()),
    ('perm-id-session-view', 'session.view', 'Xem phiên làm việc', 'Xem phiên đăng nhập hiện tại và lịch sử phiên', NOW(), NOW()),
    ('perm-id-session-revoke', 'session.revoke', 'Thu hồi phiên', 'Thu hồi phiên làm việc của bản thân hoặc người khác', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- 3. Gán Role - Permissions (Mapping chuẩn)
-- Admin: toàn quyền
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-admin', 'perm-id-user-view', NOW()),
    ('role-id-admin', 'perm-id-user-manage', NOW()),
    ('role-id-admin', 'perm-id-course-view', NOW()),
    ('role-id-admin', 'perm-id-course-manage', NOW()),
    ('role-id-admin', 'perm-id-session-view', NOW()),
    ('role-id-admin', 'perm-id-session-revoke', NOW());

-- Trainer: xem & quản lý khóa học, xem người dùng, xem phiên
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainer', 'perm-id-user-view', NOW()),
    ('role-id-trainer', 'perm-id-course-view', NOW()),
    ('role-id-trainer', 'perm-id-course-manage', NOW()),
    ('role-id-trainer', 'perm-id-session-view', NOW());

-- Trainee: xem khóa học, xem phiên
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-trainee', 'perm-id-course-view', NOW()),
    ('role-id-trainee', 'perm-id-session-view', NOW());

-- User: xem phiên
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-user', 'perm-id-session-view', NOW());
