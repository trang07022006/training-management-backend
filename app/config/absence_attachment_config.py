"""
Cấu hình và quy chuẩn lưu trữ tệp minh chứng đơn xin phép vắng (SCRUM-255 Lát 2).
Hỗ trợ:
- Tệp ảnh: JPEG, JPG, PNG, WEBP
- Tài liệu: PDF
- Giới hạn dung lượng: 5MB (5 * 1024 * 1024 bytes) mỗi tệp
- Chống XSS, SVG injection, file thực thi, file giả mạo phần mở rộng
- Sinh tên file nội bộ ngẫu nhiên UUIDv4 chống Path Traversal
"""

import io
import os
from pathlib import Path
import uuid
from PIL import Image, UnidentifiedImageError

# Thư mục gốc backend
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Thư mục lưu trữ minh chứng
DEFAULT_ATTACHMENT_UPLOAD_FOLDER = str(BACKEND_DIR / "uploads" / "absence_attachments")
ATTACHMENT_UPLOAD_FOLDER = os.getenv("ABSENCE_ATTACHMENT_UPLOAD_FOLDER", DEFAULT_ATTACHMENT_UPLOAD_FOLDER)

# Kích thước file tối đa: 5MB
ATTACHMENT_MAX_FILE_SIZE = 5 * 1024 * 1024

# Định dạng hợp lệ
ALLOWED_ATTACHMENT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}

ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}

MIME_TYPE_MAP = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "pdf": "application/pdf",
}

# Các định dạng nguy hiểm bị cấm tuyệt đối
FORBIDDEN_EXTENSIONS = {
    "svg", "html", "htm", "xml", "php", "exe", "sh", "bat", "cmd",
    "py", "js", "vbs", "ps1", "jsp", "asp", "aspx", "cgi", "jar",
}


class AttachmentValidationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def is_allowed_extension(filename: str) -> bool:
    """Kiểm tra phần mở rộng file có thuộc danh mục cho phép."""
    if not filename or not isinstance(filename, str):
        return False
    clean = filename.strip().lower()
    ext = clean.rsplit(".", 1)[-1] if "." in clean else ""
    if ext in FORBIDDEN_EXTENSIONS:
        return False
    return ext in ALLOWED_ATTACHMENT_EXTENSIONS


def is_safe_attachment_path(base_folder: str, file_path: str) -> bool:
    """Kiểm tra chống Path Traversal."""
    try:
        base = Path(base_folder).resolve()
        target = Path(file_path).resolve()
        return target.is_relative_to(base)
    except Exception:
        return False


def validate_attachment_content(filename: str, file_bytes: bytes) -> tuple[str, str, int, str]:
    """
    Xác minh tính toàn vẹn của tệp minh chứng:
    - Kiểm tra tên tệp và phần mở rộng
    - Kiểm tra dung lượng <= 5MB
    - Xác minh magic bytes:
      + Nếu PDF: header phải bắt đầu bằng %PDF-
      + Nếu ảnh: dùng Pillow xác minh định dạng JPEG, PNG hoặc WEBP
    - Trả về (safe_original_name, mime_type, file_size, internal_filename)
    """
    if not filename or not isinstance(filename, str) or not filename.strip():
        raise AttachmentValidationError("ATTACHMENT_NAME_REQUIRED", "Tên tệp minh chứng không hợp lệ.")

    clean_filename = Path(filename).name.strip()
    ext = clean_filename.rsplit(".", 1)[-1].lower() if "." in clean_filename else ""

    if ext in FORBIDDEN_EXTENSIONS or not is_allowed_extension(clean_filename):
        raise AttachmentValidationError(
            "INVALID_ATTACHMENT_TYPE",
            "Định dạng tệp không được hỗ trợ. Chỉ chấp nhận ảnh (JPG, JPEG, PNG, WEBP) hoặc tài liệu PDF.",
        )

    file_size = len(file_bytes)
    if file_size == 0:
        raise AttachmentValidationError("EMPTY_ATTACHMENT", "Tệp minh chứng không được để trống (0 byte).")

    if file_size > ATTACHMENT_MAX_FILE_SIZE:
        raise AttachmentValidationError(
            "ATTACHMENT_TOO_LARGE",
            f"Dung lượng tệp ({file_size / (1024 * 1024):.1f}MB) vượt quá giới hạn tối đa cho phép là 5MB.",
        )

    # 1. Kiểm tra tài liệu PDF
    if ext == "pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise AttachmentValidationError(
                "INVALID_ATTACHMENT_CONTENT",
                "Nội dung tệp không phải tài liệu PDF hợp lệ.",
            )
        mime_type = "application/pdf"
        internal_ext = "pdf"

    # 2. Kiểm tra ảnh (JPEG, PNG, WEBP)
    else:
        try:
            with Image.open(io.BytesIO(file_bytes)) as img:
                img_format = img.format
                if not img_format or img_format.upper() not in ALLOWED_IMAGE_FORMATS:
                    raise AttachmentValidationError(
                        "INVALID_ATTACHMENT_CONTENT",
                        "Nội dung ảnh không đúng định dạng JPG, JPEG, PNG hoặc WEBP.",
                    )
                # Map định dạng thực tế
                if img_format.upper() == "JPEG":
                    mime_type = "image/jpeg"
                    internal_ext = "jpg"
                elif img_format.upper() == "PNG":
                    mime_type = "image/png"
                    internal_ext = "png"
                elif img_format.upper() == "WEBP":
                    mime_type = "image/webp"
                    internal_ext = "webp"
                else:
                    raise AttachmentValidationError(
                        "INVALID_ATTACHMENT_CONTENT",
                        "Định dạng ảnh không được hỗ trợ.",
                    )
        except (UnidentifiedImageError, OSError):
            raise AttachmentValidationError(
                "INVALID_ATTACHMENT_CONTENT",
                "Không thể nhận diện nội dung ảnh hoặc tệp bị hỏng.",
            )

    internal_filename = f"{uuid.uuid4().hex}.{internal_ext}"
    return clean_filename, mime_type, file_size, internal_filename
