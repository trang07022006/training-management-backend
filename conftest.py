import os
import pytest
from datetime import datetime, timezone

# Pytest integration tests use a dedicated database. Never inherit the
# application's development database name from .env.
test_database_name = os.environ.get("TEST_DB_NAME", "training_management_test")
if not test_database_name.endswith("_test"):
    raise RuntimeError("TEST_DB_NAME must end with '_test' to protect shared databases")
os.environ["DB_NAME"] = test_database_name


@pytest.fixture(scope="session", autouse=True)
def seed_required_test_identities():
    """Provide fixed identities referenced by MySQL integration tests.

    Rows are insert-only and the test database suffix guard above prevents this
    fixture from targeting the development database. Passwords are deliberately
    non-authenticating placeholders; tests use JWT/session fixtures instead.
    """
    from app.database.connection import get_db_connection

    users = (
        ("34068d8d-b2ec-4ce4-977a-28ac1b9b70de", "lletrang070206@gmail.com", "Minh Trang", "admin", "role-id-admin"),
        ("demo-user-admin", "admin.demo@daotao.edu.vn", "Demo Admin", "admin", "role-id-admin"),
        ("551f6416-567b-48e4-bae4-e5f11e20da32", "test-trainee@ictu.test", "Test Trainee", "trainee", "role-id-trainee"),
        ("fd355c4c-a950-4a0b-afdb-d21c62e40470", "test-user@ictu.test", "Test User", "user", "role-id-user"),
        ("4fae5ce7-f236-443e-a93a-778db2b0e1bf", "test-consultant-a@ictu.test", "test", "consultant", "role-id-consultant"),
        ("b98111a5-6303-4de9-be69-e3059c5796a6", "test-consultant-b@ictu.test", "QA Tư vấn tuyển sinh", "consultant", "role-id-consultant"),
        ("7c50e76d-7c00-4167-b5dd-1c06df11d3e8", "test-trainer@ictu.test", "Nguyễn Văn A", "trainer", "role-id-trainer"),
        ("ebcf9c67-0cd9-4199-a0ef-35541879f25d", "test-training-manager@ictu.test", "QA Quản lý đào tạo", "training_manager", "role-id-training-manager"),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from werkzeug.security import generate_password_hash

    demo_password_hash = generate_password_hash("Demo@123456")
    connection = get_db_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            if cursor.fetchone()["database_name"] != test_database_name:
                raise RuntimeError("Test identity fixture connected to an unexpected database.")

            for user_id, email, name, role, role_id in users:
                cursor.execute(
                    """
                    INSERT IGNORE INTO users
                        (id, email, name, password_hash, role, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'active', %s, %s)
                    """,
                    (
                        user_id,
                        email,
                        name,
                        demo_password_hash if user_id == "demo-user-admin" else "!test-fixture-no-password-login!",
                        role,
                        now,
                        now,
                    ),
                )
                cursor.execute("SELECT id, email, name, role FROM users WHERE id = %s", (user_id,))
                stored_user = cursor.fetchone()
                # Migrate only the placeholder rows introduced by the first
                # version of this test fixture; never rewrite unrelated rows.
                legacy_placeholder = {
                    ("34068d8d-b2ec-4ce4-977a-28ac1b9b70de", "test-admin@ictu.test"),
                    ("demo-user-admin", "demo-admin@ictu.test"),
                }
                if stored_user and (user_id, stored_user["email"]) in legacy_placeholder:
                    cursor.execute(
                        """UPDATE users SET email = %s, name = %s,
                                  password_hash = %s WHERE id = %s""",
                        (
                            email,
                            name,
                            demo_password_hash if user_id == "demo-user-admin" else "!test-fixture-no-password-login!",
                            user_id,
                        ),
                    )
                    stored_user.update(email=email, name=name)
                if not stored_user or stored_user["role"] != role or stored_user["email"] != email:
                    raise RuntimeError(
                        f"Test identity {user_id!r} is missing or has an unexpected role; "
                        "refusing to overwrite existing test data."
                    )
                cursor.execute(
                    "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, %s)",
                    (user_id, role_id, now),
                )
            cursor.execute(
                """
                INSERT IGNORE INTO subjects
                    (id, code, name, credits, total_sessions, status, created_at, updated_at)
                VALUES
                    ('test-preserved-live-subject', 'LIVE-S1-b45466b9',
                     'Test preserved subject', 3, 10, 'active', %s, %s)
                """,
                (now, now),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

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

