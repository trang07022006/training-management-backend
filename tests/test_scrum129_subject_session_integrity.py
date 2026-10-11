"""
Bộ kiểm thử SCRUM-129 (Activity A5): Toàn vẹn dữ liệu và bảo mật (Total Sessions Integrity & Hardening).
Bao quát toàn diện:
1. Quy tắc bảo vệ hai chiều cho total_sessions:
   - Subject có các buổi học: 1..8.
   - PATCH total_sessions = 5 (< max 8) -> Bị từ chối với 409 TOTAL_SESSIONS_IN_USE.
   - PATCH total_sessions = 8 (= max 8) -> Thành công.
   - PATCH total_sessions = 10 (> max 8) -> Thành công.
   - PATCH total_sessions = None -> Thành công.
   - Subject chưa có buổi học nào -> Cập nhật mọi giá trị hợp lệ đều thành công.
2. Input Hardening:
   - Hỗ trợ đầy đủ Unicode tiếng Việt có dấu.
   - Chuỗi chứa ký tự SQL-like ("'; DROP TABLE subject_sessions; --") được lưu như text bình thường qua parameterized query.
   - Chuỗi chứa ký tự HTML-like ("<script>alert('xss')</script>") được lưu an toàn dưới dạng chuỗi thô.
3. Liên kết toàn vẹn môn học (SUBJECT_IN_USE Live):
   - Môn học có buổi học: DELETE môn học bị từ chối 409 SUBJECT_IN_USE.
   - Sau khi xóa sạch các buổi học: DELETE môn học thành công.
"""

from datetime import datetime, timezone
import unittest
import uuid

from app.database.connection import get_db_connection
from app.models.subject import Subject
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository
from app.services import subject_service, subject_session_service
from app.services.subject_service import SubjectInUseError, TotalSessionsInUseError


class Scrum129SubjectSessionIntegrityLiveTests(unittest.TestCase):
    """Kiểm thử toàn vẹn total_sessions và an toàn dữ liệu MySQL thực tế (prefix SESS-A5-)."""

    def setUp(self):
        self.subject_id = str(uuid.uuid4())
        self.subject_code = f"SESS-A5-{uuid.uuid4().hex[:6]}"
        subj = Subject(
            id=self.subject_id,
            code=self.subject_code,
            name="Môn kiểm thử Toàn vẹn A5",
            credits=3,
            total_sessions=10,
            status="active",
        )
        subject_repository.insert_subject(subj)

    def tearDown(self):
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (self.subject_id,))
                cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subject_id,))
            conn.commit()
        finally:
            conn.close()

    def test_01_total_sessions_integrity_protection(self):
        """
        Subject có session_number 1..5.
        Không thể giảm total_sessions xuống < 5.
        """
        for i in range(1, 6):
            subject_session_service.create_subject_session_service(
                self.subject_id,
                {"session_number": i, "topic": f"Buổi {i}", "objective": f"Mục tiêu {i}"},
            )

        # 1. Thử giảm xuống 4 (< max 5) -> Bị chặn 409 TOTAL_SESSIONS_IN_USE
        with self.assertRaises(TotalSessionsInUseError) as exc_info:
            subject_service.patch_subject_service(self.subject_id, {"total_sessions": 4})
        self.assertEqual(exc_info.exception.code, "TOTAL_SESSIONS_IN_USE")
        self.assertEqual(exc_info.exception.status_code, 409)

        # 2. Cập nhật bằng 5 (= max 5) -> Thành công
        res_eq = subject_service.patch_subject_service(self.subject_id, {"total_sessions": 5})
        self.assertEqual(res_eq["total_sessions"], 5)

        # 3. Tăng lên 8 (> max 5) -> Thành công
        res_gt = subject_service.patch_subject_service(self.subject_id, {"total_sessions": 8})
        self.assertEqual(res_gt["total_sessions"], 8)

        # 4. Đặt thành None (không giới hạn) -> Thành công
        res_none = subject_service.patch_subject_service(self.subject_id, {"total_sessions": None})
        self.assertIsNone(res_none["total_sessions"])

    def test_02_subject_without_sessions_can_set_any_total_sessions(self):
        """Môn học chưa có buổi học nào có thể đổi total_sessions tùy ý."""
        res1 = subject_service.patch_subject_service(self.subject_id, {"total_sessions": 2})
        self.assertEqual(res1["total_sessions"], 2)

        res2 = subject_service.patch_subject_service(self.subject_id, {"total_sessions": 0})
        self.assertEqual(res2["total_sessions"], 0)

    def test_03_unicode_and_special_character_hardening(self):
        """Kiểm thử tiếng Việt có dấu, SQL-like và HTML-like strings."""
        vietnamese_topic = "Phân tích và thiết kế thuật toán nâng cao với đồ thị có hướng"
        vietnamese_objective = "Sinh viên nắm vững thuật toán Dijkstra, Floyd-Warshall và ứng dụng thực tế."
        sql_injection_payload = "'; DROP TABLE subject_sessions; SELECT * FROM users WHERE '1'='1"
        html_xss_payload = "<script>alert('XSS_ATTACK')</script><iframe src='evil.com'></iframe>"

        # 1. Thêm session với chuỗi tiếng Việt và ký tự đặc biệt
        sess = subject_session_service.create_subject_session_service(
            self.subject_id,
            {
                "session_number": 1,
                "topic": f"{vietnamese_topic} - {sql_injection_payload}"[:255],
                "objective": f"{vietnamese_objective}\n{html_xss_payload}",
            },
        )
        self.assertIn("Dijkstra", sess["objective"])
        self.assertIn("<script>", sess["objective"])

        # Kiểm tra dữ liệu đọc lại từ DB giữ nguyên
        detail = subject_session_service.get_subject_session_detail_service(self.subject_id, sess["id"])
        self.assertEqual(detail["topic"], sess["topic"])
        self.assertEqual(detail["objective"], sess["objective"])

    def test_04_subject_in_use_live_lifecycle(self):
        """
        1. Tạo session cho môn học -> Xóa môn học ném 409 SUBJECT_IN_USE.
        2. Xóa hết session -> Xóa môn học thành công.
        """
        sess = subject_session_service.create_subject_session_service(
            self.subject_id,
            {"session_number": 1, "topic": "Buổi ngăn xóa", "objective": "Mục tiêu"},
        )

        # Xóa môn học khi có session -> 409
        with self.assertRaises(SubjectInUseError):
            subject_service.delete_subject_service(self.subject_id)

        # Xóa session
        subject_session_service.delete_subject_session_service(self.subject_id, sess["id"])

        # Xóa môn học sau khi dọn sạch session -> Thành công
        del_result = subject_service.delete_subject_service(self.subject_id)
        self.assertEqual(del_result["id"], self.subject_id)

        # Xác nhận môn học không còn trong DB
        self.assertIsNone(subject_repository.get_subject_by_id(self.subject_id))


if __name__ == "__main__":
    unittest.main()
