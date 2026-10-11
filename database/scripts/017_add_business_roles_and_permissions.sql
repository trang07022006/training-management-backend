-- Migration / Seed: 017_add_business_roles_and_permissions.sql
-- Bổ sung các vai trò nghiệp vụ: Tư vấn tuyển sinh, Quản lý đào tạo và quyền xóa Lead (SCRUM-126)
-- Đảm bảo tính idempotent: có thể chạy lại nhiều lần an toàn mà không sinh duplicate dữ liệu.

-- 1. Bổ sung các vai trò nghiệp vụ
INSERT INTO roles (id, code, name, description, created_at, updated_at)
VALUES 
    ('role-id-consultant', 'consultant', 'Tư vấn tuyển sinh', 'Tư vấn tuyển sinh và quản lý khách hàng tiềm năng', NOW(), NOW()),
    ('role-id-training-manager', 'training_manager', 'Quản lý đào tạo', 'Quản lý chương trình đào tạo và khách hàng tiềm năng', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- 2. Bổ sung quyền xóa Lead (lead.delete)
INSERT INTO permissions (id, code, name, description, created_at, updated_at)
VALUES 
    ('perm-id-lead-delete', 'lead.delete', 'Xóa khách hàng tiềm năng', 'Quyền xóa khách hàng tiềm năng trong hệ thống (chỉ dành cho Quản lý đào tạo)', NOW(), NOW())
ON DUPLICATE KEY UPDATE 
    name = VALUES(name),
    description = VALUES(description),
    updated_at = NOW();

-- 3. Gán Role - Permissions
-- Quản lý đào tạo: được quản lý Lead và ĐƯỢC xóa Lead theo SCRUM-126
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-training-manager', 'perm-id-course-view', NOW()),
    ('role-id-training-manager', 'perm-id-course-manage', NOW()),
    ('role-id-training-manager', 'perm-id-session-view', NOW()),
    ('role-id-training-manager', 'perm-id-lead-delete', NOW());

-- Tư vấn tuyển sinh: được vào module, xem/tạo/sửa Lead nhưng KHÔNG được xóa Lead
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-consultant', 'perm-id-course-view', NOW()),
    ('role-id-consultant', 'perm-id-course-manage', NOW()),
    ('role-id-consultant', 'perm-id-session-view', NOW());

-- Quản trị viên (admin): có quyền xóa Lead
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
VALUES 
    ('role-id-admin', 'perm-id-lead-delete', NOW());
