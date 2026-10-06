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

    # Cập nhật cache object
    user.avatar_path = relative_avatar_path

    # 11. Trả về payload kết quả chuẩn hóa
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
