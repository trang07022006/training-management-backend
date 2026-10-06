from dataclasses import dataclass
from datetime import date, datetime, timezone
from werkzeug.security import check_password_hash


ACCOUNT_STATUS_ACTIVE = "active"
ACCOUNT_STATUS_LOCKED = "locked"
ACCOUNT_STATUS_INACTIVE = "inactive"
VALID_ACCOUNT_STATUSES = {ACCOUNT_STATUS_ACTIVE, ACCOUNT_STATUS_LOCKED, ACCOUNT_STATUS_INACTIVE}


@dataclass
class User:
    id: str
    email: str | None = None
    password_hash: str = ""
    role: str = "user"
    status: str = "active"
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    name: str | None = None
    phone: str | None = None
    date_of_birth: date | str | None = None
    address: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_public_dict(self) -> dict:
        """Chuyển đổi thông tin người dùng an toàn ra dictionary (KHÔNG bao giờ chứa password_hash)."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "phone": self.phone,
            "role": self.role,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_profile_dict(self) -> dict:
        """Chuyển đổi thông tin hồ sơ cá nhân (SCRUM-120).
        Tuyệt đối không bao gồm password_hash, failed_login_attempts, locked_until hoặc session data."""
        dob_str = None
        if self.date_of_birth is not None:
            if hasattr(self.date_of_birth, "isoformat"):
                dob_str = self.date_of_birth.isoformat()
            else:
                dob_str = str(self.date_of_birth)

        return {
            "id": str(self.id),
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "date_of_birth": dob_str,
            "address": self.address,
            "role": self.role,
        }

    def check_password(self, password: str) -> bool:
        """Xác thực mật khẩu với password_hash của người dùng (không chấp nhận plaintext)."""
        if not isinstance(self.password_hash, str) or not self.password_hash:
            return False
        if not isinstance(password, str) or not password:
            return False
        try:
            return check_password_hash(self.password_hash, password)
        except Exception:
            return False

    def is_locked(self, current_time: datetime | None = None) -> bool:
        """Kiểm tra tài khoản có đang trong thời gian bị khóa tạm thời hay không."""
        if self.locked_until is None:
            return False
        now = current_time or datetime.now(timezone.utc)
        locked_until = self.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return now < locked_until

    def is_account_locked(self, current_time: datetime | None = None) -> bool:
        """Kiểm tra tài khoản bị khóa (khóa bởi quản trị viên hoặc khóa tạm thời)."""
        if self.status == "locked":
            return True
        return self.is_locked(current_time=current_time)

    def is_active(self, current_time: datetime | None = None) -> bool:
        """Kiểm tra tài khoản đang hoạt động bình thường."""
        return self.status == "active" and not self.is_locked(current_time=current_time)

    def is_inactive(self) -> bool:
        """Kiểm tra tài khoản ở trạng thái không hoạt động (inactive)."""
        return self.status == "inactive"
