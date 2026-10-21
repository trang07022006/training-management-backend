"""
Test suite cho SCRUM-125 - Activity A3: Public Program Options API.
Kiểm tra endpoint GET /api/v1/public/training-programs và alias GET /api/public/training-programs:
1. Không yêu cầu đăng nhập / Bearer token.
2. Chỉ trả về các chương trình có trạng thái 'active'.
3. Ẩn các chương trình 'draft' và 'archived'.
4. Trả về danh sách rỗng khi không có chương trình active nào.
5. Chỉ chứa các trường công khai tối thiểu (id, code, name, description), không leak created_at/status/updated_at.
6. Sắp xếp tất định (deterministic sorting) theo name ASC, code ASC.
7. Xử lý an toàn khi xảy ra lỗi DB (500 DATABASE_ERROR).
"""

from unittest.mock import patch
import pytest
from mysql.connector import Error as MySQLError

from app.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_public_program_options_no_auth_and_minimal_fields(client):
    """Xác nhận không yêu cầu auth và chỉ trả về các trường tối thiểu cho public."""
    fake_programs = [
        {"id": "p-1", "code": "SE01", "name": "Kỹ thuật phần mềm", "description": "Ngành hot"},
        {"id": "p-2", "code": "AI01", "name": "Trí tuệ nhân tạo", "description": None},
    ]

    with patch(
        "app.repositories.training_program_repository.get_public_active_training_programs",
        return_value=fake_programs,
    ):
        res_v1 = client.get("/api/v1/public/training-programs")
        assert res_v1.status_code == 200
        body_v1 = res_v1.get_json()
        assert body_v1["status"] == "success"
        assert len(body_v1["data"]) == 2

        # Kiểm tra cấu trúc phần tử: chỉ gồm id, code, name, description
        item = body_v1["data"][0]
        assert set(item.keys()) == {"id", "code", "name", "description"}
        assert "created_at" not in item
        assert "updated_at" not in item
        assert "status" not in item
        assert "duration_semesters" not in item

        # Kiểm tra alias
        res_alias = client.get("/api/public/training-programs")
        assert res_alias.status_code == 200
        assert res_alias.get_json() == body_v1


def test_public_program_options_empty_list(client):
    """Khi không có chương trình active nào, trả về danh sách rỗng thành công."""
    with patch(
        "app.repositories.training_program_repository.get_public_active_training_programs",
        return_value=[],
    ):
        res = client.get("/api/v1/public/training-programs")
        assert res.status_code == 200
        body = res.get_json()
        assert body["status"] == "success"
        assert body["data"] == []


def test_public_program_options_filtering_active_only():
    """Kiểm tra logic truy vấn database chỉ lấy active, sắp xếp theo name ASC, code ASC."""
    from app.repositories import training_program_repository
    from unittest.mock import MagicMock

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        {"id": "uuid-1", "code": "CS01", "name": "Khoa học máy tính", "description": "Mô tả CS"},
        {"id": "uuid-2", "code": "SE01", "name": "Kỹ thuật phần mềm", "description": "Mô tả SE"},
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.repositories.training_program_repository.get_db_connection", return_value=mock_conn):
        programs = training_program_repository.get_public_active_training_programs()

        # Kiểm tra câu lệnh SQL truy vấn có đúng điều kiện WHERE status = 'active'
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "WHERE status = 'active'" in executed_sql
        assert "ORDER BY name ASC, code ASC" in executed_sql

        assert len(programs) == 2
        assert programs[0]["code"] == "CS01"
        assert programs[1]["code"] == "SE01"
        assert "status" not in programs[0]


def test_public_program_options_database_error(client):
    """Xử lý lỗi MySQLError an toàn mà không leak stack trace."""
    with patch(
        "app.repositories.training_program_repository.get_public_active_training_programs",
        side_effect=MySQLError("Can't connect to MySQL server"),
    ):
        res = client.get("/api/v1/public/training-programs")
        assert res.status_code == 500
        body = res.get_json()
        assert body["status"] == "error"
        assert body["code"] == "DATABASE_ERROR"
        assert "MySQL" not in body["message"]


def test_public_program_options_real_database_filtering_and_order(client):
    """
    Kiểm tra trực tiếp với cơ sở dữ liệu thật MySQL:
    - Ẩn chương trình 'draft' và 'archived'
    - Chỉ hiển thị 'active'
    - Sắp xếp tất định theo name ASC, code ASC
    """
    import uuid
    from app.database.connection import get_db_connection

    prog_active_1 = {
        "id": str(uuid.uuid4()),
        "code": "PROG-A3-ACT-Z",
        "name": "Z - Ngành Z",
        "status": "active",
    }
    prog_active_2 = {
        "id": str(uuid.uuid4()),
        "code": "PROG-A3-ACT-A",
        "name": "A - Ngành A",
        "status": "active",
    }
    prog_draft = {
        "id": str(uuid.uuid4()),
        "code": "PROG-A3-DRF",
        "name": "Ngành Dự thảo",
        "status": "draft",
    }
    prog_archived = {
        "id": str(uuid.uuid4()),
        "code": "PROG-A3-ARC",
        "name": "Ngành Đã lưu trữ",
        "status": "archived",
    }

    test_progs = [prog_active_1, prog_active_2, prog_draft, prog_archived]

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            for p in test_progs:
                cursor.execute(
                    """
                    INSERT INTO training_programs (id, code, name, description, duration_semesters, status, created_at, updated_at)
                    VALUES (%s, %s, %s, 'Mô tả test A3', 8, %s, NOW(), NOW())
                    """,
                    (p["id"], p["code"], p["name"], p["status"]),
                )
        conn.commit()

        # Gọi API công khai không auth
        res = client.get("/api/v1/public/training-programs")
        assert res.status_code == 200
        data = res.get_json()["data"]

        returned_ids = [item["id"] for item in data]
        assert prog_active_1["id"] in returned_ids
        assert prog_active_2["id"] in returned_ids
        assert prog_draft["id"] not in returned_ids
        assert prog_archived["id"] not in returned_ids

        # Kiểm tra thứ tự A - Ngành A trước Z - Ngành Z
        idx_a = returned_ids.index(prog_active_2["id"])
        idx_z = returned_ids.index(prog_active_1["id"])
        assert idx_a < idx_z

    finally:
        with conn.cursor() as cursor:
            for p in test_progs:
                cursor.execute("DELETE FROM training_programs WHERE id = %s", (p["id"],))
        conn.commit()
        conn.close()
