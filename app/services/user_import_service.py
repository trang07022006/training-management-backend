"""
Service hỗ trợ bulk import người dùng qua Excel (SCRUM-119).
Activity A1: Tạo file Excel mẫu cho bulk import người dùng.
Activity A2: Upload và đọc dữ liệu từ sheet Users của file Excel.
"""

from io import BytesIO
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill


USER_IMPORT_TEMPLATE_HEADERS = [
    "name",
    "email",
    "password",
    "phone",
    "role",
    "status",
]

USER_IMPORT_TEMPLATE_FILENAME = "user_import_template.xlsx"
EXCEL_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class UserImportError(Exception):
    """Lỗi xử lý file Excel import người dùng."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _format_cell_value(val) -> str | None:
    """Format giá trị cell thành chuỗi string sạch, xử lý float int."""
    if val is None:
        return None
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    s = str(val).strip()
    return s if s else None


def generate_user_import_template() -> BytesIO:
    """
    Tạo file Excel mẫu (.xlsx) phục vụ import người dùng (Activity A1).
    - Sheet 1 ('Users'): chứa header chuẩn theo contract tạo user và 1 dòng dữ liệu mẫu an toàn.
    - Sheet 2 ('Huong_Dan'): mô tả chi tiết quy định từng trường, ràng buộc bắt buộc và giá trị hợp lệ.
    """
    wb = openpyxl.Workbook()

    # --- Sheet 1: Users ---
    ws_users = wb.active
    ws_users.title = "Users"

    # Header styling
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    center_align = Alignment(horizontal="center", vertical="center")

    ws_users.append(USER_IMPORT_TEMPLATE_HEADERS)
    for col_idx in range(1, len(USER_IMPORT_TEMPLATE_HEADERS) + 1):
        cell = ws_users.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align

    # Dữ liệu mẫu minh họa an toàn (không chứa mật khẩu thật hay email thật nhạy cảm)
    sample_row = [
        "Nguyen Van A",
        "example.user@daotao.edu.vn",
        "DemoUser@123",
        "0912345678",
        "trainee",
        "active",
    ]
    ws_users.append(sample_row)

    # Đặt độ rộng cột cho dễ nhìn
    column_widths = {
        "A": 25,  # name
        "B": 32,  # email
        "C": 18,  # password
        "D": 18,  # phone
        "E": 15,  # role
        "F": 15,  # status
    }
    for col_letter, width in column_widths.items():
        ws_users.column_dimensions[col_letter].width = width

    # --- Sheet 2: Huong_Dan ---
    ws_guide = wb.create_sheet(title="Huong_Dan")
    guide_headers = ["Tên cột (Header)", "Bắt buộc", "Kiểu dữ liệu", "Quy tắc và giá trị hợp lệ", "Mô tả"]
    ws_guide.append(guide_headers)

    guide_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
    guide_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    for col_idx in range(1, len(guide_headers) + 1):
        cell = ws_guide.cell(row=1, column=col_idx)
        cell.fill = guide_fill
        cell.font = guide_font
        cell.alignment = center_align

    guide_data = [
        ("name", "Bắt buộc", "Chuỗi ký tự", "Không được để trống", "Họ và tên người dùng"),
        ("email", "Bắt buộc", "Email", "Định dạng email hợp lệ, tối đa 255 ký tự, không trùng lặp trong hệ thống", "Địa chỉ email đăng nhập"),
        ("password", "Bắt buộc", "Chuỗi ký tự", "Tối thiểu 8 ký tự, phải bao gồm cả chữ cái và chữ số", "Mật khẩu khởi tạo ban đầu"),
        ("phone", "Tùy chọn", "Số điện thoại", "9-15 chữ số (vd: 0912345678 hoặc +84912345678)", "Số điện thoại liên hệ"),
        ("role", "Tùy chọn", "Mã vai trò", "admin | trainer | trainee | user (mặc định: user)", "Vai trò chính của tài khoản"),
        ("status", "Tùy chọn", "Trạng thái", "active | inactive | locked (mặc định: active)", "Trạng thái kích hoạt của tài khoản"),
    ]
    for row in guide_data:
        ws_guide.append(list(row))

    guide_column_widths = {"A": 20, "B": 15, "C": 18, "D": 45, "E": 35}
    for col_letter, width in guide_column_widths.items():
        ws_guide.column_dimensions[col_letter].width = width

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def parse_user_import_workbook(file_stream, filename: str | None = None) -> dict:
    """
    Đọc và parse dữ liệu từ workbook Excel .xlsx (Activity A2).
    - Kiểm tra định dạng .xlsx
    - Kiểm tra file không rỗng và không bị hỏng
    - Mở sheet 'Users'
    - Kiểm tra cấu trúc header đúng chuẩn contract
    - Bỏ qua các dòng trống hoàn toàn
    - Giữ nguyên số dòng Excel thực tế (row_number)
    - Trả về danh sách preview an toàn (không để lộ mật khẩu plaintext)
    - Giữ _internal_rows phục vụ các Activity xử lý tiếp theo
    """
    if file_stream is None:
        raise UserImportError("FILE_REQUIRED", "Vui lòng chọn file tải lên.")

    fname = getattr(file_stream, "filename", None) or filename or ""
    if not fname or not fname.lower().endswith(".xlsx"):
        raise UserImportError("INVALID_FILE_TYPE", "Chỉ chấp nhận file định dạng Excel (.xlsx).")

    if hasattr(file_stream, "seek"):
        file_stream.seek(0)

    content = file_stream.read() if hasattr(file_stream, "read") else file_stream
    if not content or len(content) == 0:
        raise UserImportError("FILE_EMPTY", "File tải lên rỗng.")

    try:
        wb = openpyxl.load_workbook(BytesIO(content), data_only=True)
    except Exception:
        raise UserImportError("INVALID_EXCEL_FILE", "File Excel không hợp lệ hoặc bị hỏng.")

    if "Users" not in wb.sheetnames:
        raise UserImportError("MISSING_USERS_SHEET", "File Excel thiếu sheet 'Users'.")

    ws = wb["Users"]
    rows_iter = ws.iter_rows(values_only=True)

    try:
        header_row = next(rows_iter, None)
    except Exception:
        raise UserImportError("INVALID_EXCEL_FILE", "Không thể đọc dữ liệu từ sheet 'Users'.")

    if not header_row:
        raise UserImportError("INVALID_HEADER", "Sheet 'Users' không có tiêu đề cột.")

    # Đọc và chuẩn hóa header (loại bỏ các cột trống ở cuối nếu có)
    cleaned_headers = []
    for val in header_row:
        if val is not None and str(val).strip():
            cleaned_headers.append(str(val).strip().lower())
        else:
            break

    if cleaned_headers != USER_IMPORT_TEMPLATE_HEADERS:
        raise UserImportError("INVALID_HEADER", "Cấu trúc tiêu đề (header) của sheet Users không đúng mẫu quy định.")

    parsed_rows = []
    preview_rows = []
    row_index = 1  # Hàng 1 là header

    for row in rows_iter:
        row_index += 1
        # Cắt lấy các cột tương ứng với template header
        row_values = list(row[: len(USER_IMPORT_TEMPLATE_HEADERS)])
        if len(row_values) < len(USER_IMPORT_TEMPLATE_HEADERS):
            row_values += [None] * (len(USER_IMPORT_TEMPLATE_HEADERS) - len(row_values))

        cleaned_cells = [_format_cell_value(c) for c in row_values]

        # Bỏ qua dòng hoàn toàn trống
        if all(c is None for c in cleaned_cells):
            continue

        name_val, email_val, password_val, phone_val, role_val, status_val = cleaned_cells

        internal_record = {
            "row_number": row_index,
            "name": name_val or "",
            "email": email_val or "",
            "password": password_val or "",
            "phone": phone_val,
            "role": role_val,
            "status": status_val,
        }
        parsed_rows.append(internal_record)

        # Preview record: KHÔNG chứa plaintext password
        preview_record = {
            "row_number": row_index,
            "name": name_val or "",
            "email": email_val or "",
            "phone": phone_val,
            "role": role_val,
            "status": status_val,
            "password_present": bool(password_val),
        }
        preview_rows.append(preview_record)

    if not parsed_rows:
        raise UserImportError("NO_DATA", "File Excel không chứa dòng dữ liệu nào để import.")

    return {
        "filename": fname,
        "headers": list(USER_IMPORT_TEMPLATE_HEADERS),
        "total_rows": len(parsed_rows),
        "rows": preview_rows,
        "_internal_rows": parsed_rows,
    }
