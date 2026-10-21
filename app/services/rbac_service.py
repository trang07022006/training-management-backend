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
    Permission(id="perm-id-schedule-view", code="schedule.view", name="Xem thời khóa biểu", description="Xem thời khóa biểu và lịch giảng dạy/học tập toàn trường"),
    Permission(id="perm-id-schedule-manage", code="schedule.manage", name="Quản lý thời khóa biểu", description="Tạo, sửa, hủy và điều chỉnh lịch học, thời khóa biểu"),
    Permission(id="perm-id-schedule-personal-view", code="schedule.personal_view", name="Xem lịch cá nhân", description="Xem thời khóa biểu cá nhân của học viên hoặc lịch giảng dạy của giảng viên"),
    Permission(id="perm-id-assignment-view", code="assignment.view", name="Xem bài tập", description="Xem danh sách bài tập và bài nộp"),
    Permission(id="perm-id-assignment-grade", code="assignment.grade", name="Chấm và yêu cầu làm lại bài", description="Chấm bài và gửi yêu cầu làm lại bài tập"),
    Permission(id="perm-id-assignment-submit", code="assignment.submit", name="Nộp bài tập", description="Nộp bài và nộp lại bài tập"),
]

# Danh mục mapping quyền cho từng vai trò
INITIAL_ROLE_PERMISSIONS_MAP = {
    "admin": [
        "user.view", "user.manage", "course.view", "course.manage",
        "session.view", "session.revoke",
        "schedule.view", "schedule.personal_view",
        "assignment.view", "assignment.grade",
    ],
    "trainer": [
        "course.view", "course.manage", "session.view",
        "schedule.view", "schedule.personal_view",
        "assignment.view", "assignment.grade",
    ],
    "trainee": [
        "course.view", "session.view",
        "schedule.personal_view",
        "assignment.view", "assignment.submit",
    ],
    "user": ["session.view"],
}

# Danh mục định nghĩa các vai trò nghiệp vụ mở rộng (SCRUM-126)
BUSINESS_ROLES = [
    Role(id="role-id-consultant", code="consultant", name="Tư vấn tuyển sinh", description="Tư vấn tuyển sinh và quản lý khách hàng tiềm năng"),
    Role(id="role-id-training-manager", code="training_manager", name="Quản lý đào tạo", description="Quản lý chương trình đào tạo và khách hàng tiềm năng"),
]

BUSINESS_PERMISSIONS = [
    Permission(id="perm-id-lead-delete", code="lead.delete", name="Xóa khách hàng tiềm năng", description="Quyền xóa khách hàng tiềm năng trong hệ thống (chỉ dành cho Quản lý đào tạo)"),
]

BUSINESS_ROLE_PERMISSIONS_MAP = {
    "training_manager": [
        "user.view", "course.view", "course.manage", "session.view", "lead.delete",
        "schedule.view", "schedule.manage", "schedule.personal_view",
        "assignment.view", "assignment.grade",
    ],
    "consultant": ["course.view", "course.manage", "session.view"],
    "admin": ["lead.delete"],
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


def sync_business_rbac_data() -> dict:
    """
    Khởi tạo và đồng bộ các vai trò và quyền hạn nghiệp vụ mới (SCRUM-126).
    Đảm bảo tính idempotent, an toàn khi chạy nhiều lần.
    """
    now = datetime.now(timezone.utc)
    roles_created = 0
    permissions_created = 0
    mappings_created = 0

    # 1. Đồng bộ Business Roles
    for role in BUSINESS_ROLES:
        existing = role_repository.get_role_by_code(role.code)
        if not existing:
            role.created_at = now
            role.updated_at = now
            role_repository.insert_role(role)
            roles_created += 1

    # 2. Đồng bộ Business Permissions
    for perm in BUSINESS_PERMISSIONS:
        existing = permission_repository.get_permission_by_code(perm.code)
        if not existing:
            perm.created_at = now
            perm.updated_at = now
            permission_repository.insert_permission(perm)
            permissions_created += 1

    # 3. Đồng bộ Mapping Business Role - Permissions
    for role_code, perm_codes in BUSINESS_ROLE_PERMISSIONS_MAP.items():
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

    return {
        "roles_created": roles_created,
        "permissions_created": permissions_created,
        "mappings_created": mappings_created,
    }

