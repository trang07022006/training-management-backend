"""
Service hỗ trợ bulk import người dùng qua Excel (SCRUM-119).
Activity A1: Tạo file Excel mẫu cho bulk import người dùng.
Activity A2: Upload và đọc dữ liệu từ sheet Users của file Excel.
Activity A3: Validate từng dòng dữ liệu Excel và trả preview lỗi chi tiết.
"""

from io import BytesIO
import re
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from app.repositories import user_repository
from app.services import user_service
from app.services.user_service import (
    EMAIL_REGEX,
    PHONE_REGEX,
    VALID_ROLES,
    VALID_STATUSES,
    DuplicateEmailError,
    UserValidationError,
    normalize_email,
)


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


def validate_import_rows(raw_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Validate từng dòng dữ liệu sau khi đọc từ Excel (SCRUM-119 Activity A3).
    - Kiểm tra bắt buộc: name, email, password
    - Kiểm tra định dạng: email, phone, password policy
    - Kiểm tra hợp lệ: role, status
    - Áp dụng giá trị mặc định cho role (user) và status (active) nếu để trống
    - Kiểm tra email trùng lặp trong nội bộ file và trùng lặp với DB
    - Trả về (preview_rows, internal_rows) với trạng thái valid và danh sách errors chi tiết
    """
    preview_rows = []
    internal_rows = []
    seen_emails_in_file: set[str] = set()

    for item in raw_rows:
        row_idx = item.get("row_number", 0)
        raw_name = item.get("name")
        raw_email = item.get("email")
        raw_password = item.get("password")
        raw_phone = item.get("phone")
        raw_role = item.get("role")
        raw_status = item.get("status")

        errors: list[dict] = []

        # 1. Validate NAME (bắt buộc, không để trống)
        cleaned_name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else ""
        if not cleaned_name:
            errors.append({
                "field": "name",
                "code": "NAME_REQUIRED",
                "message": "Họ và tên không được để trống.",
            })

        # 2. Validate EMAIL (bắt buộc, đúng định dạng, không trùng file, không trùng DB)
        norm_email = ""
        email_str = raw_email.strip() if isinstance(raw_email, str) else ""
        if not email_str:
            errors.append({
                "field": "email",
                "code": "EMAIL_REQUIRED",
                "message": "Email là bắt buộc.",
            })
        else:
            norm_email = normalize_email(email_str)
            if len(norm_email) > 255 or not EMAIL_REGEX.match(norm_email):
                errors.append({
                    "field": "email",
                    "code": "INVALID_EMAIL",
                    "message": "Email không đúng định dạng.",
                })
            else:
                # Kiểm tra trùng lặp trong file
                if norm_email in seen_emails_in_file:
                    errors.append({
                        "field": "email",
                        "code": "DUPLICATE_EMAIL_IN_FILE",
                        "message": f"Email '{norm_email}' bị trùng lặp với dòng khác trong file.",
                    })
                else:
                    seen_emails_in_file.add(norm_email)
                    # Kiểm tra trùng lặp trong cơ sở dữ liệu
                    try:
                        if user_repository.check_email_exists(norm_email):
                            errors.append({
                                "field": "email",
                                "code": "DUPLICATE_EMAIL",
                                "message": "Email này đã được sử dụng trong hệ thống.",
                            })
                    except Exception:
                        pass

        # 3. Validate PASSWORD (bắt buộc, policy >= 8 ký tự, có cả chữ và số)
        password_str = str(raw_password) if raw_password is not None else ""
        password_present = bool(password_str.strip())
        if not password_str:
            errors.append({
                "field": "password",
                "code": "PASSWORD_REQUIRED",
                "message": "Mật khẩu là bắt buộc.",
            })
        else:
            if len(password_str) < 8:
                errors.append({
                    "field": "password",
                    "code": "PASSWORD_TOO_SHORT",
                    "message": "Mật khẩu phải có tối thiểu 8 ký tự.",
                })
            elif not re.search(r"[a-zA-Z]", password_str) or not re.search(r"[0-9]", password_str):
                errors.append({
                    "field": "password",
                    "code": "PASSWORD_INVALID",
                    "message": "Mật khẩu phải bao gồm cả chữ cái và chữ số.",
                })

        # 4. Validate PHONE (tùy chọn; nếu có thì 9-15 chữ số)
        cleaned_phone = None
        if raw_phone is not None and str(raw_phone).strip():
            phone_candidate = str(raw_phone).strip()
            if not PHONE_REGEX.match(phone_candidate):
                errors.append({
                    "field": "phone",
                    "code": "INVALID_PHONE",
                    "message": "Số điện thoại không hợp lệ (cần 9-15 chữ số).",
                })
            else:
                cleaned_phone = phone_candidate

        # 5. Validate ROLE (tùy chọn, mặc định "user", chỉ nhận admin, trainer, trainee, user)
        if raw_role is None or str(raw_role).strip() == "":
            selected_role = "user"
        else:
            selected_role = str(raw_role).strip().lower()
            if selected_role not in VALID_ROLES:
                errors.append({
                    "field": "role",
                    "code": "INVALID_ROLE",
                    "message": f"Vai trò không hợp lệ: {raw_role}.",
                })

        # 6. Validate STATUS (tùy chọn, mặc định "active", chỉ nhận active, inactive, locked)
        if raw_status is None or str(raw_status).strip() == "":
            selected_status = "active"
        else:
            selected_status = str(raw_status).strip().lower()
            if selected_status not in VALID_STATUSES:
                errors.append({
                    "field": "status",
                    "code": "INVALID_STATUS",
                    "message": f"Trạng thái không hợp lệ: {raw_status}.",
                })

        is_valid = len(errors) == 0

        # Public preview record: KHÔNG chứa plaintext password
        preview_rows.append({
            "row_number": row_idx,
            "name": cleaned_name,
            "email": norm_email or email_str,
            "phone": cleaned_phone,
            "role": selected_role,
            "status": selected_status,
            "password_present": password_present,
            "valid": is_valid,
            "errors": errors,
        })

        # Internal record: Giữ password phục vụ Activity import
        internal_rows.append({
            "row_number": row_idx,
            "name": cleaned_name,
            "email": norm_email or email_str,
            "password": password_str,
            "phone": cleaned_phone,
            "role": selected_role,
            "status": selected_status,
            "valid": is_valid,
            "errors": errors,
        })

    return preview_rows, internal_rows


def parse_user_import_workbook(file_stream, filename: str | None = None) -> dict:
    """
    Đọc và parse dữ liệu từ workbook Excel .xlsx (Activity A2 & A3).
    - Kiểm tra định dạng .xlsx
    - Kiểm tra file không rỗng và không bị hỏng
    - Mở sheet 'Users'
    - Kiểm tra cấu trúc header đúng chuẩn contract
    - Bỏ qua các dòng trống hoàn toàn
    - Giữ nguyên số dòng Excel thực tế (row_number)
    - Validate từng dòng dữ liệu và gắn danh sách errors chi tiết (Activity A3)
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

    raw_rows = []
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

        raw_rows.append({
            "row_number": row_index,
            "name": name_val or "",
            "email": email_val or "",
            "password": password_val or "",
            "phone": phone_val,
            "role": role_val,
            "status": status_val,
        })

    if not raw_rows:
        raise UserImportError("NO_DATA", "File Excel không chứa dòng dữ liệu nào để import.")

    # Validate từng dòng và thống kê hợp lệ (Activity A3)
    preview_rows, internal_rows = validate_import_rows(raw_rows)
    valid_count = sum(1 for r in preview_rows if r["valid"])
    invalid_count = len(preview_rows) - valid_count

    return {
        "filename": fname,
        "headers": list(USER_IMPORT_TEMPLATE_HEADERS),
        "total_rows": len(preview_rows),
        "valid_rows": valid_count,
        "invalid_rows": invalid_count,
        "rows": preview_rows,
        "_internal_rows": internal_rows,
    }


def execute_user_import(file_stream, filename: str | None = None) -> dict:
    """
    Thực hiện import các dòng hợp lệ vào cơ sở dữ liệu (SCRUM-119 Activity A4).
    - Parse và validate workbook bằng logic A2/A3
    - Duyệt qua từng dòng dữ liệu:
      - Dòng invalid -> bỏ qua, không ghi DB, lưu errors
      - Dòng valid -> tạo user qua create_user_service (hash mật khẩu, gán role, kiểm tra duplicate)
      - Lỗi từng dòng (nếu có) không làm rollback các dòng thành công khác (partial success)
    - Trả về kết quả tổng hợp import an toàn (không lộ plaintext password)
    """
    parse_result = parse_user_import_workbook(file_stream, filename=filename)
    internal_rows = parse_result.get("_internal_rows", [])

    imported_rows_count = 0
    skipped_rows_count = 0
    result_rows = []

    for row in internal_rows:
        row_number = row["row_number"]
        name = row["name"]
        email = row["email"]
        password = row["password"]
        phone = row["phone"]
        role = row["role"]
        status = row["status"]
        is_valid = row.get("valid", False)
        initial_errors = list(row.get("errors", []))

        if not is_valid:
            # Dòng không hợp lệ từ bước validate -> bỏ qua, không ghi DB
            skipped_rows_count += 1
            result_rows.append({
                "row_number": row_number,
                "name": name,
                "email": email,
                "role": role,
                "status": status,
                "imported": False,
                "errors": initial_errors,
            })
            continue

        # Dòng hợp lệ -> tiến hành ghi DB từng dòng độc lập
        try:
            user_service.create_user_service(
                email=email,
                password=password,
                name=name,
                phone=phone,
                role=role,
                status=status,
            )
            imported_rows_count += 1
            result_rows.append({
                "row_number": row_number,
                "name": name,
                "email": email,
                "role": role,
                "status": status,
                "imported": True,
                "errors": [],
            })
        except DuplicateEmailError:
            skipped_rows_count += 1
            result_rows.append({
                "row_number": row_number,
                "name": name,
                "email": email,
                "role": role,
                "status": status,
                "imported": False,
                "errors": [{
                    "field": "email",
                    "code": "DUPLICATE_EMAIL",
                    "message": "Email này đã được sử dụng trong hệ thống.",
                }],
            })
        except UserValidationError as e:
            skipped_rows_count += 1
            result_rows.append({
                "row_number": row_number,
                "name": name,
                "email": email,
                "role": role,
                "status": status,
                "imported": False,
                "errors": [{
                    "field": "validation",
                    "code": e.code,
                    "message": e.message,
                }],
            })
        except Exception:
            skipped_rows_count += 1
            result_rows.append({
                "row_number": row_number,
                "name": name,
                "email": email,
                "role": role,
                "status": status,
                "imported": False,
                "errors": [{
                    "field": "database",
                    "code": "IMPORT_FAILED",
                    "message": "Lỗi khi lưu người dùng vào cơ sở dữ liệu.",
                }],
            })

    return {
        "filename": parse_result.get("filename", filename or ""),
        "total_rows": len(result_rows),
        "imported_rows": imported_rows_count,
        "skipped_rows": skipped_rows_count,
        "rows": result_rows,
    }
