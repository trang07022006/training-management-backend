import pytest
from app.services.auth_service import clear_forgot_password_rate_limits
from app.services.lead_service import clear_consultation_rate_limits


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Tự động dọn sạch rate limit bộ nhớ trước và sau mỗi test."""
    clear_forgot_password_rate_limits()
    clear_consultation_rate_limits()
    yield
    clear_forgot_password_rate_limits()
    clear_consultation_rate_limits()
