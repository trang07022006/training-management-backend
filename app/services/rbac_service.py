from datetime import datetime, timezone

from app.models.permission import Permission
from app.models.role import Role
from app.repositories import (
    permission_repository,
    role_permission_repository,
    role_repository,
    user_role_repository,
)

# Danh mục định nghĩa các vai trò chuẩn trong hệ thống
INITIAL_ROLES = [
    Role(id="role-id-admin", code="admin", name="Quản trị viên", description="Toàn quyền quản trị hệ thống và người dùng"),
    Role(id="role-id-trainer", code="trainer", name="Giảng viên", description="Quản lý khóa đào tạo, học viên và điểm danh"),
    Role(id="role-id-trainee", code="trainee", name="Học viên", description="Tham gia các khóa đào tạo và theo dõi tiến độ"),
    Role(id="role-id-user", code="user", name="Người dùng", description="Người dùng thông thường trong hệ thống"),
]

# Danh mục định nghĩa các quyền hạn chuẩn trong hệ thống
INITIAL_PERMISSIONS = [
    Permission(id="perm-id-user-view", code="user.view", name="Xem người dùng", description="Xem danh sách và thông tin tài khoản người dùng"),
    Permission(id="perm-id-user-manage", code="user.manage", name="Quản trị người dùng", description="Thêm, sửa, khóa hoặc phân quyền người dùng"),
    Permission(id="perm-id-course-view", code="course.view", name="Xem khóa học", description="Xem chương trình và nội dung đào tạo"),
    Permission(id="perm-id-course-manage", code="course.manage", name="Quản trị khóa học", description="Tạo, sửa và cập nhật tài liệu đào tạo"),
    Permission(id="perm-id-session-view", code="session.view", name="Xem phiên làm việc", description="Xem phiên đăng nhập hiện tại và lịch sử phiên"),
    Permission(id="perm-id-session-revoke", code="session.revoke", name="Thu hồi phiên", description="Thu hồi phiên làm việc của bản thân hoặc người khác"),
]

# Danh mục mapping quyền cho từng vai trò
INITIAL_ROLE_PERMISSIONS_MAP = {
    "admin": ["user.view", "user.manage", "course.view", "course.manage", "session.view", "session.revoke"],
    "trainer": ["course.view", "course.manage", "session.view"],
    "trainee": ["course.view", "session.view"],
    "user": ["session.view"],
}


def sync_initial_rbac_data() -> dict:
    """
    Khởi tạo và đồng bộ dữ liệu RBAC ban đầu theo cơ chế idempotent (SCRUM-64).
    Chạy nhiều lần không gây lỗi trùng lặp và không làm mất dữ liệu người dùng.
    """
    now = datetime.now(timezone.utc)
    roles_created = 0
    permissions_created = 0
    mappings_created = 0

    # 1. Đồng bộ Roles
    for role in INITIAL_ROLES:
        existing = role_repository.get_role_by_code(role.code)
        if not existing:
            role.created_at = now
            role.updated_at = now
            role_repository.insert_role(role)
            roles_created += 1

    # 2. Đồng bộ Permissions
    for perm in INITIAL_PERMISSIONS:
        existing = permission_repository.get_permission_by_code(perm.code)
        if not existing:
            perm.created_at = now
            perm.updated_at = now
            permission_repository.insert_permission(perm)
            permissions_created += 1

    # 3. Đồng bộ Mapping Role - Permissions
    for role_code, perm_codes in INITIAL_ROLE_PERMISSIONS_MAP.items():
        role = role_repository.get_role_by_code(role_code)
        if not role:
            continue
        existing_perm_codes = set(role_permission_repository.get_permission_codes_by_role_id(role.id))
        for p_code in perm_codes:
            if p_code not in existing_perm_codes:
                perm = permission_repository.get_permission_by_code(p_code)
                if perm:
                    role_permission_repository.assign_permission_to_role(role.id, perm.id)
                    mappings_created += 1

        # Thu hồi các quyền đã bị loại khỏi cấu hình chuẩn của vai trò
        for p_code in existing_perm_codes:
            if p_code not in perm_codes:
                perm = permission_repository.get_permission_by_code(p_code)
                if perm:
                    role_permission_repository.remove_permission_from_role(role.id, perm.id)

    return {
        "roles_created": roles_created,
        "permissions_created": permissions_created,
        "mappings_created": mappings_created,
    }


def get_user_permissions(user_id: str) -> list[str]:
    """
    Lấy toàn bộ danh sách mã quyền hạn (permission codes) của người dùng
    bằng cách tổng hợp quyền từ tất cả các vai trò mà người dùng sở hữu (SCRUM-64).
    """
    roles = user_role_repository.get_roles_by_user_id(user_id)
    all_permissions = set()

    for role in roles:
        codes = role_permission_repository.get_permission_codes_by_role_id(role.id)
        all_permissions.update(codes)

    return sorted(list(all_permissions))


def user_has_permission(user_id: str, permission_code: str) -> bool:
    """
    Kiểm tra xem người dùng có quyền cụ thể hay không (SCRUM-64).
    """
    permissions = get_user_permissions(user_id)
    return permission_code in permissions
