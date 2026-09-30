"""
Dịch vụ Quản trị Vai trò Người dùng (User Role Service - SCRUM-96 -> SCRUM-100).
Xử lý nghiệp vụ:
- Đọc danh sách vai trò của một người dùng (SCRUM-96)
- Lấy danh mục các vai trò khả dụng trong hệ thống (SCRUM-97)
- Phân vai trò cho người dùng với cơ chế chống trùng lặp an toàn (SCRUM-98)
- Gỡ vai trò khỏi người dùng với kiểm tra ràng buộc (SCRUM-99)
- Đồng bộ primary role trên bảng users để tương thích ngược session/login (SCRUM-18/SCRUM-25)
"""

import logging
from mysql.connector import IntegrityError

from app.models.role import Role
from app.repositories import role_repository, user_repository, user_role_repository

logger = logging.getLogger(__name__)


class UserRoleServiceError(Exception):
    """Lớp lỗi cơ sở cho UserRoleService."""
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class UserNotFoundError(UserRoleServiceError):
    def __init__(self, message: str = "Không tìm thấy người dùng."):
        super().__init__("USER_NOT_FOUND", message, status_code=404)


class RoleNotFoundError(UserRoleServiceError):
    def __init__(self, message: str = "Không tìm thấy vai trò."):
        super().__init__("ROLE_NOT_FOUND", message, status_code=404)


class DuplicateRoleAssignmentError(UserRoleServiceError):
    def __init__(self, message: str = "Người dùng đã được gán vai trò này."):
        super().__init__("DUPLICATE_ROLE_ASSIGNMENT", message, status_code=409)


class RoleNotAssignedError(UserRoleServiceError):
    def __init__(self, message: str = "Người dùng chưa được gán vai trò này."):
        super().__init__("ROLE_NOT_ASSIGNED", message, status_code=404)


class RoleValidationError(UserRoleServiceError):
    def __init__(self, message: str = "Dữ liệu vai trò không hợp lệ."):
        super().__init__("INVALID_ROLE", message, status_code=400)


def _serialize_role(role: Role) -> dict:
    """Chuyển đối tượng Role thành dictionary công khai an toàn (không leak internal permissions)."""
    return {
        "id": str(role.id),
        "code": str(role.code),
        "name": str(role.name),
        "description": role.description or "",
    }


def get_user_roles(user_id: str) -> dict:
    """
    Lấy danh sách vai trò hiện tại của một người dùng (SCRUM-96).
    - Validate user_id tồn tại, nếu không -> UserNotFoundError (404).
    - Trả về danh sách roles không chứa internals nhạy cảm.
    """
    if not user_id or not isinstance(user_id, str):
        raise UserNotFoundError()

    clean_user_id = user_id.strip()
    user = user_repository.get_user_by_id(clean_user_id)
    if user is None:
        raise UserNotFoundError()

    roles = user_role_repository.get_roles_by_user_id(clean_user_id)
    serialized_roles = [_serialize_role(r) for r in roles]

    return {
        "user_id": clean_user_id,
        "roles": serialized_roles,
    }


def get_available_roles() -> list[dict]:
    """
    Lấy danh mục các vai trò khả dụng trong hệ thống từ database (SCRUM-97).
    """
    roles = role_repository.get_all_roles()
    return [_serialize_role(r) for r in roles]


def _resolve_role(role_id_or_code: str) -> Role:
    """Tìm Role theo ID hoặc theo Code."""
    if not role_id_or_code or not isinstance(role_id_or_code, str):
        raise RoleValidationError("Mã hoặc ID vai trò là bắt buộc.")

    clean_val = role_id_or_code.strip()
    if not clean_val:
        raise RoleValidationError("Mã hoặc ID vai trò không được để trống.")

    # Tìm theo ID trước
    role = role_repository.get_role_by_id(clean_val)
    if role is not None:
        return role

    # Tìm theo Code
    role = role_repository.get_role_by_code(clean_val.lower())
    if role is not None:
        return role

    raise RoleNotFoundError(f"Không tìm thấy vai trò: {clean_val}.")


def assign_role_to_user(user_id: str, role_id_or_code: str) -> dict:
    """
    Phân vai trò cho người dùng (SCRUM-98).
    - Validate user tồn tại
    - Validate role tồn tại
    - Chống duplicate mapping (trả về 409 DUPLICATE_ROLE_ASSIGNMENT)
    - Cập nhật primary role của user nếu cần
    """
    if not user_id or not isinstance(user_id, str):
        raise UserNotFoundError()

    clean_user_id = user_id.strip()
    user = user_repository.get_user_by_id(clean_user_id)
    if user is None:
        raise UserNotFoundError()

    role = _resolve_role(role_id_or_code)

    # Kiểm tra mapping đã tồn tại chưa
    if user_role_repository.check_user_role_exists(clean_user_id, role.id):
        raise DuplicateRoleAssignmentError(f"Người dùng '{user.email or clean_user_id}' đã có vai trò '{role.name}'.")

    # Gán vai trò (có phòng thủ IntegrityError nếu có race condition)
    try:
        user_role_repository.assign_role_to_user(clean_user_id, role.id)
    except IntegrityError:
        raise DuplicateRoleAssignmentError(f"Người dùng '{user.email or clean_user_id}' đã có vai trò '{role.name}'.")

    # Đồng bộ primary role trên users table (tương thích backward với Login token)
    primary_code = user_role_repository.get_primary_role_code_by_user_id(clean_user_id)
    if primary_code and primary_code != user.role:
        user.role = primary_code
        try:
            user_repository.update_user(user)
        except Exception as e:
            logger.warning("Không thể cập nhật primary role trên bảng users: %s", e)

    return {
        "user_id": clean_user_id,
        "role": _serialize_role(role),
    }


def revoke_role_from_user(user_id: str, role_id_or_code: str) -> dict:
    """
    Gỡ vai trò khỏi người dùng (SCRUM-99).
    - Validate user tồn tại
    - Validate role tồn tại
    - Validate mapping tồn tại (nếu chưa gán -> 404 ROLE_NOT_ASSIGNED)
    - Đồng bộ lại primary role trên users table
    """
    if not user_id or not isinstance(user_id, str):
        raise UserNotFoundError()

    clean_user_id = user_id.strip()
    user = user_repository.get_user_by_id(clean_user_id)
    if user is None:
        raise UserNotFoundError()

    role = _resolve_role(role_id_or_code)

    # Kiểm tra mapping có tồn tại không
    if not user_role_repository.check_user_role_exists(clean_user_id, role.id):
        raise RoleNotAssignedError(f"Người dùng '{user.email or clean_user_id}' chưa được gán vai trò '{role.name}'.")

    # Xóa vai trò
    deleted = user_role_repository.remove_role_from_user(clean_user_id, role.id)
    if not deleted:
        raise RoleNotAssignedError(f"Người dùng '{user.email or clean_user_id}' chưa được gán vai trò '{role.name}'.")

    # Đồng bộ lại primary role
    primary_code = user_role_repository.get_primary_role_code_by_user_id(clean_user_id) or "user"
    if primary_code != user.role:
        user.role = primary_code
        try:
            user_repository.update_user(user)
        except Exception as e:
            logger.warning("Không thể cập nhật primary role trên bảng users sau khi gỡ: %s", e)

    return {
        "user_id": clean_user_id,
        "role_id": str(role.id),
        "role_code": str(role.code),
    }
