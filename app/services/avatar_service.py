"""
Dịch vụ xử lý ảnh đại diện người dùng (User Avatar Service - SCRUM-121 - Activity A2).
Bao gồm:
- Xác minh file upload (multipart/form-data)
- Kiểm tra dung lượng thực tế tối đa 2MB
- Xác minh nội dung ảnh thực tế (Pillow verify format JPEG/PNG/WEBP)
- Chống SVG injection, HTML/XSS, file giả mạo, file thực thi
- Sinh tên file UUIDv4 ngẫu nhiên và ngăn ngừa Path Traversal
- Lưu trữ an toàn và cập nhật đường dẫn tương đối (POSIX-style) vào MySQL
- Dọn dẹp (cleanup) file trên đĩa nếu thao tác cơ sở dữ liệu thất bại
"""

import io
import logging
import os
import uuid
from pathlib import Path
from flask import current_app
from PIL import Image, UnidentifiedImageError

from app.config.avatar_config import (
    ALLOWED_AVATAR_MIME_TYPES,
    AVATAR_MAX_FILE_SIZE,
    AVATAR_UPLOAD_FOLDER,
    FORBIDDEN_AVATAR_EXTENSIONS,
    is_allowed_avatar_extension,
    is_safe_avatar_path,
)
from app.repositories import user_repository
from app.services.user_service import UserNotFoundError

logger = logging.getLogger(__name__)

FORMAT_MAP = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


class AvatarError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AvatarRequiredError(AvatarError):
    def __init__(self, message: str = "Vui lòng chọn tệp ảnh đại diện."):
        super().__init__(code="AVATAR_REQUIRED", message=message, status_code=400)


class AvatarTooLargeError(AvatarError):
    def __init__(self, message: str = "Ảnh đại diện không được vượt quá 2 MB."):
        super().__init__(code="AVATAR_TOO_LARGE", message=message, status_code=400)


class InvalidAvatarTypeError(AvatarError):
    def __init__(self, message: str = "Định dạng ảnh không hợp lệ. Chỉ chấp nhận JPG, JPEG, PNG, WEBP."):
        super().__init__(code="INVALID_AVATAR_TYPE", message=message, status_code=400)


class AvatarUploadError(AvatarError):
    def __init__(self, message: str = "Không thể tải lên ảnh đại diện."):
        super().__init__(code="AVATAR_UPLOAD_FAILED", message=message, status_code=500)


class AvatarNotFoundError(AvatarError):
    def __init__(self, message: str = "Người dùng chưa có ảnh đại diện."):
        super().__init__(code="AVATAR_NOT_FOUND", message=message, status_code=404)


def upload_user_avatar_service(user_id: str, file_storage) -> dict:
    """
    Xử lý tải lên ảnh đại diện cho người dùng đang đăng nhập (SCRUM-121 A2).
    - Xác định user từ user_id session (tuyệt đối không nhận từ client request)
    - Kiểm tra tính toàn vẹn và dung lượng tệp
    - Xác minh chữ ký nhị phân ảnh (Pillow)
    - Sinh UUID ngẫu nhiên và lưu file an toàn
    - Cập nhật database và dọn dẹp file nếu database lỗi
    """
    # 1. Xác thực người dùng
    if not isinstance(user_id, str) or not user_id.strip():
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    user = user_repository.get_user_by_id(user_id.strip())
    if user is None:
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    old_avatar_path = user.avatar_path

    # 2. Kiểm tra sự tồn tại của file trong request
    if file_storage is None:
        raise AvatarRequiredError()

    filename = getattr(file_storage, "filename", None)
    if not filename or not isinstance(filename, str) or not filename.strip():
        raise AvatarRequiredError()

    clean_filename = filename.strip()

    # 3. Kiểm tra phần mở rộng file ban đầu (whitelist & blacklist)
    ext = clean_filename.rsplit(".", 1)[-1].lower() if "." in clean_filename else ""
    if ext in FORBIDDEN_AVATAR_EXTENSIONS or not is_allowed_avatar_extension(clean_filename):
        raise InvalidAvatarTypeError()

    # 4. Kiểm tra MIME type nếu client gửi lên
    content_type = getattr(file_storage, "content_type", None) or getattr(file_storage, "mimetype", None)
    if content_type:
        clean_mime = content_type.strip().lower()
        if clean_mime in {
            "image/svg+xml",
            "text/html",
            "text/plain",
            "application/x-executable",
            "application/x-msdownload",
            "application/pdf",
            "application/javascript",
        }:
            raise InvalidAvatarTypeError()

    # 5. Đọc dữ liệu nhị phân thực tế để kiểm tra dung lượng
    try:
        file_bytes = file_storage.read()
    except Exception as err:
        logger.error(f"Lỗi khi đọc file avatar: {err}")
        raise AvatarUploadError("Không thể đọc tệp dữ liệu ảnh tải lên.")

    if not file_bytes or len(file_bytes) == 0:
        raise AvatarRequiredError("Tệp ảnh rỗng. Vui lòng chọn tệp ảnh hợp lệ.")

    # Giới hạn kích thước thực tế tối đa 2MB
    max_size = (
        current_app.config.get("AVATAR_MAX_FILE_SIZE", AVATAR_MAX_FILE_SIZE)
        if current_app
        else AVATAR_MAX_FILE_SIZE
    )
    if len(file_bytes) > max_size:
        raise AvatarTooLargeError()

    # 6. Xác minh nội dung ảnh thực tế (Image verification via Pillow)
    try:
        img = Image.open(io.BytesIO(file_bytes))
        img.verify()
        actual_format = img.format  # "JPEG", "PNG", "WEBP"
    except (UnidentifiedImageError, Exception) as err:
        logger.warning(f"File avatar không thể xác minh bằng Pillow: {err}")
        raise InvalidAvatarTypeError("Tệp không phải là ảnh hợp lệ hoặc nội dung đã bị lỗi.")

    if actual_format not in FORMAT_MAP:
        raise InvalidAvatarTypeError(
            f"Định dạng ảnh {actual_format} không được hỗ trợ. Chỉ chấp nhận JPG, JPEG, PNG, WEBP."
        )

    # Lấy phần mở rộng chuẩn từ định dạng thực tế đã xác minh
    verified_extension = FORMAT_MAP[actual_format]

    # 7. Sinh tên file ngẫu nhiên UUIDv4
    random_filename = f"{uuid.uuid4()}.{verified_extension}"

    # 8. Xác định thư mục lưu trữ đích
    upload_folder_str = (
        current_app.config.get("AVATAR_UPLOAD_FOLDER", AVATAR_UPLOAD_FOLDER)
        if current_app
        else AVATAR_UPLOAD_FOLDER
    )
    upload_folder = Path(upload_folder_str).resolve()
    upload_folder.mkdir(parents=True, exist_ok=True)

    target_path = (upload_folder / random_filename).resolve()

    # Kiểm tra Path Traversal
    if not is_safe_avatar_path(str(upload_folder), str(target_path)):
        raise AvatarError("INVALID_PATH", "Đường dẫn lưu trữ tệp không an toàn.")

    # 9. Ghi file ra đĩa
    try:
        target_path.write_bytes(file_bytes)
    except Exception as err:
        logger.error(f"Lỗi khi ghi file avatar ra đĩa: {err}")
        raise AvatarUploadError("Không thể lưu tệp ảnh vào hệ thống lưu trữ.")

    # Đường dẫn tương đối POSIX lưu vào MySQL
    relative_avatar_path = f"avatars/{random_filename}"

    # 10. Cập nhật đường dẫn avatar vào cơ sở dữ liệu với cơ chế cleanup an toàn
    try:
        updated = user_repository.update_user_avatar(user.id, relative_avatar_path)
        if not updated:
            # Dọn dẹp file vừa tạo nếu database update không thành công
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            raise AvatarUploadError("Không thể cập nhật đường dẫn ảnh vào cơ sở dữ liệu.")
    except Exception as db_err:
        # Cleanup file lập tức nếu có bất kỳ lỗi database nào xảy ra
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        if isinstance(db_err, AvatarUploadError):
            raise
        logger.error(f"Lỗi database khi cập nhật avatar: {db_err}")
        raise AvatarUploadError("Lỗi cơ sở dữ liệu khi cập nhật ảnh đại diện.")

    # 11. Xóa avatar cũ an toàn (SCRUM-121 A3: chỉ xóa sau khi DB đã cập nhật thành công)
    if old_avatar_path and old_avatar_path != relative_avatar_path:
        delete_avatar_file(old_avatar_path, upload_folder_str)

    # Cập nhật cache object
    user.avatar_path = relative_avatar_path

    # 12. Trả về payload kết quả chuẩn hóa
    return {
        "status": "success",
        "message": "Cập nhật ảnh đại diện thành công.",
        "avatar": {
            "path": relative_avatar_path,
        },
        "data": {
            "avatar_path": relative_avatar_path,
        },
    }


def delete_avatar_file(avatar_path: str, upload_folder_str: str) -> bool:
    """
    Xóa file ảnh đại diện trên đĩa một cách an toàn (SCRUM-121 - Activity A3).
    Chỉ xóa nếu:
    - avatar_path là chuỗi hợp lệ
    - target path nằm strictly bên trong upload_folder (không phải chính upload_folder)
    - target path tồn tại và là file thông thường (is_file)
    Tuyệt đối không xóa file ngoài uploads/avatars/ kể cả khi DB chứa path traversal (../../) hay absolute path.
    Nếu file không tồn tại hoặc có lỗi filesystem: ghi log, trả về False, không raise exception.
    """
    if not avatar_path or not isinstance(avatar_path, str):
        return False

    clean_path = avatar_path.strip().replace("\\", "/")
    if clean_path.startswith("avatars/"):
        relative_part = clean_path[len("avatars/"):]
    else:
        relative_part = clean_path

    try:
        upload_folder = Path(upload_folder_str).resolve()
        target = (upload_folder / relative_part).resolve()

        # Không được phép là chính thư mục upload
        if target == upload_folder:
            logger.warning(f"Từ chối xóa avatar: target là chính upload root ({target})")
            return False

        # Phải nằm hoàn toàn bên trong upload_folder (ngăn chặn path traversal)
        if not target.is_relative_to(upload_folder):
            logger.warning(f"Từ chối xóa avatar: target nằm ngoài upload root ({target})")
            return False

        # Kiểm tra file có tồn tại trên đĩa không
        if not target.is_file():
            logger.info(f"File avatar không tồn tại trên đĩa để xóa: {target}")
            return False

        target.unlink()
        logger.info(f"Đã xóa file avatar thành công: {target}")
        return True
    except Exception as err:
        logger.warning(f"Lỗi filesystem khi xóa file avatar ({avatar_path}): {err}")
        return False


def delete_user_avatar_service(user_id: str) -> dict:
    """
    Xóa ảnh đại diện của người dùng (SCRUM-121 - Activity A3).
    - Lấy user từ database
    - Nếu user không có avatar_path: trả về thành công (idempotent)
    - Cập nhật database trước: avatar_path = NULL, updated_at = now
    - Sau khi database cập nhật thành công: xóa file cũ trên đĩa an toàn
    - Nếu xóa file trên đĩa gặp lỗi: DB vẫn giữ NULL, không rollback, log warning
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    user = user_repository.get_user_by_id(user_id.strip())
    if user is None:
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    old_avatar_path = user.avatar_path

    # Nếu hiện tại người dùng chưa có avatar: idempotent thành công
    if not old_avatar_path:
        return {
            "status": "success",
            "message": "Đã xóa ảnh đại diện.",
            "avatar": None,
            "data": {
                "avatar_path": None,
            },
        }

    # 1. Cập nhật database trước: đặt avatar_path = NULL
    try:
        updated = user_repository.clear_user_avatar(user.id)
        if not updated:
            raise AvatarUploadError("Không thể cập nhật cơ sở dữ liệu khi xóa ảnh đại diện.")
    except Exception as db_err:
        if isinstance(db_err, AvatarError):
            raise
        logger.error(f"Lỗi database khi clear avatar: {db_err}")
        raise AvatarUploadError("Lỗi cơ sở dữ liệu khi xóa ảnh đại diện.")

    # Cập nhật cache object
    user.avatar_path = None

    # 2. Xóa file trên đĩa sau khi DB đã thành công
    upload_folder_str = (
        current_app.config.get("AVATAR_UPLOAD_FOLDER", AVATAR_UPLOAD_FOLDER)
        if current_app
        else AVATAR_UPLOAD_FOLDER
    )
    delete_avatar_file(old_avatar_path, upload_folder_str)

    return {
        "status": "success",
        "message": "Đã xóa ảnh đại diện.",
        "avatar": None,
        "data": {
            "avatar_path": None,
        },
    }


def get_user_avatar_file(user_id: str) -> tuple[Path, str]:
    """
    Truy xuất tệp ảnh đại diện an toàn cho người dùng (SCRUM-121 - Activity A4).
    - Xác định user từ database
    - Kiểm tra avatar_path
    - Xác minh đường dẫn an toàn (nằm strictly trong uploads/avatars/)
    - Kiểm tra định dạng hợp lệ (jpg/png/webp) và ánh xạ MIME type
    - Kiểm tra sự tồn tại của file trên đĩa
    - Trả về (Path, mimetype) hoặc raise AvatarNotFoundError
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    user = user_repository.get_user_by_id(user_id.strip())
    if user is None:
        raise UserNotFoundError("Không tìm thấy thông tin người dùng.")

    if not user.avatar_path or not isinstance(user.avatar_path, str) or not user.avatar_path.strip():
        raise AvatarNotFoundError("Người dùng chưa có ảnh đại diện.")

    clean_path = user.avatar_path.strip().replace("\\", "/")
    if clean_path.startswith("avatars/"):
        relative_part = clean_path[len("avatars/"):]
    else:
        relative_part = clean_path

    # Kiểm tra extension hợp lệ
    ext = relative_part.rsplit(".", 1)[-1].lower() if "." in relative_part else ""
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    if ext not in mime_map:
        logger.warning(f"Avatar file có định dạng không được phép: {user.avatar_path}")
        raise AvatarNotFoundError("Định dạng ảnh đại diện không hợp lệ.")

    upload_folder_str = (
        current_app.config.get("AVATAR_UPLOAD_FOLDER", AVATAR_UPLOAD_FOLDER)
        if current_app
        else AVATAR_UPLOAD_FOLDER
    )
    upload_folder = Path(upload_folder_str).resolve()
    target = (upload_folder / relative_part).resolve()

    # Kiểm tra target không phải là thư mục upload root
    if target == upload_folder:
        logger.warning(f"Từ chối serve avatar: target là chính upload root ({target})")
        raise AvatarNotFoundError("Không tìm thấy ảnh đại diện.")

    # Phải nằm hoàn toàn bên trong upload_folder (ngăn chặn path traversal, absolute external path, symlink escape)
    try:
        if not target.is_relative_to(upload_folder):
            logger.warning(f"Từ chối serve avatar: target nằm ngoài upload root ({target})")
            raise AvatarNotFoundError("Không tìm thấy ảnh đại diện.")
    except (ValueError, RuntimeError):
        raise AvatarNotFoundError("Không tìm thấy ảnh đại diện.")

    # Kiểm tra file có tồn tại trên đĩa và là file thông thường
    if not target.is_file():
        logger.warning(f"File avatar trong DB ({user.avatar_path}) không tồn tại trên đĩa: {target}")
        raise AvatarNotFoundError("Không tìm thấy ảnh đại diện.")

    return target, mime_map[ext]


