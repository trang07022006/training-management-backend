"""
Kiểm thử tính toàn vẹn và tương tranh phân công Lead (SCRUM-127 - Activity A3).
Bao gồm:
1. Tính toàn vẹn dữ liệu: Khi xóa người dùng được phân công trong bảng users,
   MySQL kích hoạt ràng buộc ON DELETE SET NULL:
   - Bản ghi Lead KHÔNG bị xóa (không mất Lead).
   - assigned_to_user_id tự động chuyển thành NULL.
   - get_lead_by_id trả về assigned_to_user_id = None, assigned_to_name = None.
2. Tương tranh (Concurrency): Nhiều tác vụ phân công liên tiếp cùng một Lead,
   dữ liệu ghi nhận đúng giá trị cuối cùng (last-write-wins), không xảy ra race condition làm mất Lead.
3. Hoạt động của Public Consultation: Đảm bảo luồng tạo yêu cầu tư vấn công khai
   không bị ảnh hưởng, Lead mới tạo có assigned_to_user_id = NULL.
"""

from datetime import datetime, timezone
import uuid
import pytest

from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_NEW,
    Lead,
)
from app.repositories import lead_repository
from app.services import lead_service


class TestLeadAssignmentIntegrityAndConcurrency:
    """Kiểm thử toàn vẹn khóa ngoại và tương tranh phân công Lead."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.created_lead_ids = []
        self.created_user_ids = []
        yield
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass
        for uid in self.created_user_ids:
            try:
                conn = get_db_connection()
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (uid,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def _create_temp_user(self, role: str = "trainer") -> str:
        uid = str(uuid.uuid4())
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, role, status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (uid, f"User {uid[:8]}", f"user_{uid[:8]}@ictu.edu.vn", "hash", role, "active"),
                )
            conn.commit()
        finally:
            conn.close()
        self.created_user_ids.append(uid)
        return uid

    def test_on_delete_set_null_integrity(self):
        """Khi user được phân công bị xóa khỏi bảng users, Lead phải giữ nguyên và assigned_to_user_id thành NULL."""
        user_id = self._create_temp_user(role="trainer")

        lid = str(uuid.uuid4())
        lead = Lead(
            id=lid,
            full_name="Nguyễn Văn Học Viên",
            phone="0911223344",
            email="hocvien@ictu.edu.vn",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)

        # Phân công
        updated = lead_repository.assign_lead(lid, user_id)
        assert updated is not None
        assert updated.assigned_to_user_id == user_id

        # Xóa user khỏi bảng users
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
        finally:
            conn.close()

        # Kiểm tra Lead vẫn tồn tại nhưng assigned_to_user_id = None
        fetched = lead_repository.get_lead_by_id(lid)
        assert fetched is not None
        assert fetched.id == lid
        assert fetched.full_name == "Nguyễn Văn Học Viên"
        assert fetched.assigned_to_user_id is None
        assert fetched.assigned_to_name is None

    def test_concurrency_last_write_wins(self):
        """Hai admin phân công nối tiếp nhau, ghi nhận giá trị cuối cùng an toàn."""
        u1 = self._create_temp_user(role="trainer")
        u2 = self._create_temp_user(role="admin")

        lid = str(uuid.uuid4())
        lead = Lead(
            id=lid,
            full_name="Nguyễn Văn Tương Tranh",
            phone="0922334455",
            email="tuongtranh@ictu.edu.vn",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)
        self.created_lead_ids.append(lid)

        # Admin 1 assign
        res1 = lead_service.assign_lead_service(lid, {"user_id": u1})
        assert res1["data"]["assigned_to_user_id"] == u1

        # Admin 2 assign ngay sau đó
        res2 = lead_service.assign_lead_service(lid, {"user_id": u2})
        assert res2["data"]["assigned_to_user_id"] == u2

        fetched = lead_repository.get_lead_by_id(lid)
        assert fetched is not None
        assert fetched.assigned_to_user_id == u2

    def test_public_consultation_unaffected(self):
        """Tạo yêu cầu tư vấn công khai không gán người phụ trách mặc định (assigned_to_user_id là None)."""
        payload = {
            "full_name": "Trần Thị Tư Vấn Công Khai",
            "phone": "0933445566",
            "email": "tuvan_pub@gmail.com",
            "message": "Tôi muốn đăng ký tư vấn tuyển sinh.",
        }
        res = lead_service.create_public_consultation_service(payload)
        lead_id = res["data"]["id"]
        self.created_lead_ids.append(lead_id)

        fetched = lead_repository.get_lead_by_id(lead_id)
        assert fetched is not None
        assert fetched.status == "new"
        assert fetched.assigned_to_user_id is None
        assert fetched.assigned_at is None
