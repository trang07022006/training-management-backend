from dataclasses import dataclass
from datetime import datetime


@dataclass
class LoginSession:
    session_id: str
    user_id: str
    refresh_jti: str
    created_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None