from dataclasses import dataclass
from werkzeug.security import check_password_hash


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    role: str = "user"
    status: str = "active"

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

