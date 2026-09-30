import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv


def configure_jwt(app):
    backend_dir = Path(__file__).resolve().parents[2]
    load_dotenv(backend_dir / ".env")

    secret_key = os.getenv("JWT_SECRET_KEY", "").strip()

    if len(secret_key.encode("utf-8")) < 32:
        raise ValueError(
            "JWT_SECRET_KEY phải có ít nhất 32 byte. "
            "Hãy kiểm tra file backend/.env."
        )

    try:
        access_minutes = int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "15"))
        refresh_hours = int(os.getenv("JWT_REFRESH_TOKEN_HOURS", "8"))
        idle_minutes = int(os.getenv("SESSION_IDLE_TIMEOUT_MINUTES", "30"))
    except ValueError as error:
        raise ValueError("Các thời hạn JWT phải là số nguyên.") from error

    if min(access_minutes, refresh_hours, idle_minutes) <= 0:
        raise ValueError("Các thời hạn JWT phải lớn hơn 0.")

    if not access_minutes <= idle_minutes <= refresh_hours * 60:
        raise ValueError(
            "Thời hạn phải thỏa: access token <= không hoạt động <= refresh token."
        )

    app.config.update(
        JWT_SECRET_KEY=secret_key,
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=access_minutes),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(hours=refresh_hours),
        SESSION_IDLE_TIMEOUT=timedelta(minutes=idle_minutes),
    )