from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class PasswordResetToken:
    id: str
    user_id: str
    token_hash: str
    created_at: datetime
    expires_at: datetime

    def is_expired(self, current_time: datetime | None = None) -> bool:
        """Kiểm tra token đã hết hạn 30 phút hay chưa."""
        now = current_time or datetime.now(timezone.utc)
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return now >= expires_at
