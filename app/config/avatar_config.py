"""
Cấu hình và quy chuẩn lưu trữ ảnh đại diện người dùng (SCRUM-121 - Activity A1).
Chuẩn bị nền tảng cấu hình và thiết kế an ninh cho chức năng Avatar (A2).
"""

import os
import uuid
from pathlib import Path

# Thư mục gốc backend
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Thư mục lưu trữ avatar mặc định
DEFAULT_AVATAR_UPLOAD_FOLDER = str(BACKEND_DIR / "uploads" / "avatars")
AVATAR_UPLOAD_FOLDER = os.getenv("AVATAR_UPLOAD_FOLDER", DEFAULT_AVATAR_UPLOAD_FOLDER)

# Kích thước file tối đa: 2MB (2 * 1024 * 1024 bytes)
AVATAR_MAX_FILE_SIZE = 2 * 1024 * 1024

# Định dạng ảnh hợp lệ dự kiến cho A2
ALLOWED_AVATAR_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_AVATAR_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

# Các định dạng tuyệt đối cấm (chống XSS, SVG injection, executable upload)
FORBIDDEN_AVATAR_EXTENSIONS = {
    "svg",
    "html",
    "htm",
    "xml",
    "php",
    "exe",
    "sh",
    "bat",
    "cmd",
    "py",
    "js",
}


def is_allowed_avatar_extension(filename_or_ext: str) -> bool:
    """
    Kiểm tra phần mở rộng file có thuộc danh mục ảnh cho phép (jpg, jpeg, png, webp).
    Tuyệt đối từ chối SVG, HTML, file thực thi.
    """
    if not filename_or_ext or not isinstance(filename_or_ext, str):
        return False

    clean = filename_or_ext.strip().lower()
    ext = clean.rsplit(".", 1)[-1] if "." in clean else clean

    if ext in FORBIDDEN_AVATAR_EXTENSIONS:
        return False

    return ext in ALLOWED_AVATAR_EXTENSIONS


def generate_avatar_filename(extension: str) -> str:
    """
    Sinh tên file ngẫu nhiên bằng UUIDv4 để chống xung đột và path traversal.
    Tuyệt đối không sử dụng tên file gốc do người dùng gửi lên.
    """
    ext = extension.strip().lower().lstrip(".")
    if not is_allowed_avatar_extension(ext):
        raise ValueError(f"Định dạng ảnh không được phép: {ext}")

    return f"{uuid.uuid4()}.{ext}"


def is_safe_avatar_path(base_folder: str, file_path: str) -> bool:
    """
    Kiểm tra đường dẫn file có nằm hoàn toàn bên trong thư mục upload chỉ định (chống Path Traversal).
    """
    try:
        base = Path(base_folder).resolve()
        target = Path(file_path).resolve()
        return target.is_relative_to(base)
    except (ValueError, RuntimeError):
        return False


def configure_avatar(app) -> None:
    """
    Nạp các thông số cấu hình avatar vào Flask app.config.
    """
    upload_folder = os.getenv("AVATAR_UPLOAD_FOLDER", DEFAULT_AVATAR_UPLOAD_FOLDER)
    try:
        max_size = int(os.getenv("AVATAR_MAX_FILE_SIZE", str(AVATAR_MAX_FILE_SIZE)))
    except (ValueError, TypeError):
        max_size = AVATAR_MAX_FILE_SIZE

    app.config.update(
        AVATAR_UPLOAD_FOLDER=upload_folder,
        AVATAR_MAX_FILE_SIZE=max_size,
        ALLOWED_AVATAR_EXTENSIONS=ALLOWED_AVATAR_EXTENSIONS,
        ALLOWED_AVATAR_MIME_TYPES=ALLOWED_AVATAR_MIME_TYPES,
    )
