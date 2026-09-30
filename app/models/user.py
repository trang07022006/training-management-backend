from dataclasses import dataclass
from datetime import datetime, timezone
from werkzeug.security import check_password_hash


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    role: str = "user"
    status: str = "active"
    failed_login_attempts: int = 0
    locked_until: datetime | None = None

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


