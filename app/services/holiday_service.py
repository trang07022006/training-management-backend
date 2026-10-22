"""
Service nghiệp vụ Quản lý ngày nghỉ lễ (Holiday Service) - SCRUM-224.
"""

from datetime import date, datetime
from typing import Any
from app.models.holiday import Holiday
from app.repositories.holiday_repository import (
    delete_holiday,
    get_holiday_by_date,
    get_holiday_by_id,
    insert_holiday,
    list_holidays,
)


class HolidayServiceError(Exception):
    def __init__(self, message: str, code: str = "HOLIDAY_ERROR", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def parse_date(date_val: Any) -> date:
    """Chuyển đổi chuỗi YYYY-MM-DD hoặc date thành đối tượng date."""
    if isinstance(date_val, date) and not isinstance(date_val, datetime):
        return date_val
    if isinstance(date_val, datetime):
        return date_val.date()
    if isinstance(date_val, str):
        try:
            return datetime.strptime(date_val.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HolidayServiceError(
                "Định dạng ngày không hợp lệ. Vui lòng sử dụng định dạng YYYY-MM-DD.",
                code="INVALID_DATE_FORMAT",
                status_code=400,
            )
    raise HolidayServiceError(
        "Ngày nghỉ lễ không được để trống.",
        code="MISSING_DATE",
        status_code=400,
    )


def create_holiday_service(data: dict[str, Any]) -> dict[str, Any]:
    """Khai báo ngày nghỉ lễ mới (SCRUM-224)."""
    raw_date = data.get("holiday_date")
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()

    if not name:
        raise HolidayServiceError("Tên ngày nghỉ lễ không được để trống.", code="MISSING_NAME", status_code=400)

    holiday_date = parse_date(raw_date)

    # Kiểm tra trùng ngày nghỉ lễ
    existing = get_holiday_by_date(holiday_date)
    if existing:
        raise HolidayServiceError(
            f"Ngày nghỉ lễ {holiday_date.strftime('%d/%m/%Y')} đã tồn tại trong hệ thống.",
            code="HOLIDAY_ALREADY_EXISTS",
            status_code=409,
        )

    holiday = Holiday(
        id="",
        holiday_date=holiday_date,
        name=name,
        description=description if description else None,
    )
    saved = insert_holiday(holiday)
    return saved.to_dict()


def list_holidays_service(
    from_date_str: str | None = None,
    to_date_str: str | None = None,
) -> list[dict[str, Any]]:
    """Lấy danh sách các ngày nghỉ lễ đã khai báo."""
    from_date = parse_date(from_date_str) if from_date_str else None
    to_date = parse_date(to_date_str) if to_date_str else None

    holidays = list_holidays(from_date=from_date, to_date=to_date)
    return [h.to_dict() for h in holidays]


def delete_holiday_service(holiday_id: str) -> None:
    """Xóa ngày nghỉ lễ theo ID."""
    existing = get_holiday_by_id(holiday_id)
    if not existing:
        raise HolidayServiceError("Ngày nghỉ lễ không tồn tại.", code="HOLIDAY_NOT_FOUND", status_code=404)
    delete_holiday(holiday_id)
