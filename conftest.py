import os
import pytest
from app.services.auth_service import clear_forgot_password_rate_limits
from app.services.lead_service import clear_consultation_rate_limits

os.environ.setdefault("STUDENT_INITIAL_PASSWORD", "TestStudent@2026")


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Tự động dọn sạch rate limit bộ nhớ trước và sau mỗi test."""
    clear_forgot_password_rate_limits()
    clear_consultation_rate_limits()
    yield
    clear_forgot_password_rate_limits()
    clear_consultation_rate_limits()

