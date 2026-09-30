"""
Dịch vụ kiểm tra và xác thực quyền hạn (RBAC Authorization Service) (SCRUM-70).
Nguyên tắc:
1. Source of Truth: Database là nguồn dữ liệu quyết định quyền hạn cuối cùng.
2. Không tin tưởng dữ liệu client gửi lên (role/permissions trong payload, header hay query).
3. Default Deny: Mọi trường hợp không xác định được quyền hạn rõ ràng đều bị từ chối (DENY).
4. Xử lý lỗi Database an toàn, tuyệt đối không chuyển lỗi thành ALLOW.
"""

from typing import List, Set
from mysql.connector import Error as MySQLError

from app.repositories import (
    permission_repository,
    role_permission_repository,
    role_repository,
    user_repository,
    user_role_repository,
)


def get_user_permissions(user_id: str) -> list[str]:
    """
    Lấy toàn bộ danh sách mã quyền hạn (permission codes) hiện tại của người dùng từ Database.
    Tổng hợp quyền từ tất cả các vai trò (roles) mà người dùng sở hữu.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        return []

    # 1. Lấy danh sách roles của user từ bảng user_roles
    roles = user_role_repository.get_roles_by_user_id(user_id)

    # 2. Nếu chưa có trong user_roles, kiểm tra role của user trong bảng users (SCRUM-18 compatibility)
    if not roles:
        user = user_repository.get_user_by_id(user_id)
        if user and user.role:
            role = role_repository.get_role_by_code(user.role)
            if role:
                roles = [role]

    if not roles:
        return []

    # 3. Lấy tất cả permission codes từ các roles của người dùng
    all_permissions: Set[str] = set()
    for role in roles:
        if role and role.id:
            codes = role_permission_repository.get_permission_codes_by_role_id(role.id)
            all_permissions.update(codes)

    return sorted(list(all_permissions))


def has_permission(user_id: str, permission_code: str) -> bool:
    """
    Kiểm tra xem người dùng có quyền cụ thể hay không (SCRUM-70).
    Áp dụng nguyên tắc Default Deny:
    - user_id không hợp lệ -> False
    - permission_code không hợp lệ hoặc không tồn tại trong hệ thống -> False
    - user không có role -> False
    - role không có permission -> False
    """
    if not isinstance(user_id, str) or not user_id.strip():
        return False

    if not isinstance(permission_code, str) or not permission_code.strip():
        return False

    # Kiểm tra xem permission_code có tồn tại trong danh mục permissions của hệ thống không
    perm = permission_repository.get_permission_by_code(permission_code)
    if not perm:
        return False

    permissions = get_user_permissions(user_id)
    return permission_code in permissions


# Alias hỗ trợ quy ước đặt tên
check_user_permission = has_permission
