"""
Bộ kiểm thử tự động cho SCRUM-255 Lát cắt 255.2 — Đính kèm và kiểm soát minh chứng đơn xin phép vắng.
Kiểm tra:
1. Gửi đơn kèm minh chứng hợp lệ (ảnh PNG/JPG, tài liệu PDF) -> lưu trữ thành công, trả về metadata.
2. Tải/xem minh chứng:
   - Chủ đơn (học viên A) xem được (200).
   - Giảng viên phụ trách buổi học xem được (200).
   - Quản lý đào tạo xem được (200).
   - Học viên khác (học viên B) bị chặn (403).
   - Không xác thực bị chặn (401).
   - Tệp không tồn tại -> (404).
3. Kiểm tra validation minh chứng:
   - Dung lượng > 5MB bị chặn (400 ATTACHMENT_TOO_LARGE).
   - Đuôi tệp cấm (.exe, .html, .svg) bị chặn (400 INVALID_ATTACHMENT_TYPE).
   - Giả mạo nội dung (đuôi .jpg nhưng nội dung là HTML/text) bị chặn (400 INVALID_ATTACHMENT_CONTENT).
   - Hơn 5 tệp đính kèm bị chặn (400 TOO_MANY_ATTACHMENTS).
4. Chống tệp mồ côi: khi tạo đơn thất bại (duplicate pending, lỗi payload), tệp đã ghi tạm thời phải được dọn dẹp sạch sẽ khỏi đĩa.
"""

from datetime import date, datetime, timedelta
import io
import os
from pathlib import Path
import unittest
import uuid
from PIL import Image

from flask_jwt_extended import create_access_token

from app.config.absence_attachment_config import ATTACHMENT_UPLOAD_FOLDER
from app.database.connection import get_db_connection
from app.main import app
from app.repositories.absence_request_repository import VIETNAM_TZ


def _create_minimal_png_bytes() -> bytes:
    """Tạo một file ảnh PNG 10x10 hợp lệ bằng Pillow."""
    img = Image.new("RGB", (10, 10), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_minimal_pdf_bytes() -> bytes:
    """Tạo nội dung PDF tối thiểu hợp lệ."""
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000115 00000 n\ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n190\n%%EOF"


class Scrum255Slice2AttachmentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls.client = app.test_client()

        cls.suffix = uuid.uuid4().hex[:8]
        cls.admin_user_id = f"test-admin-{cls.suffix}"
        cls.training_mgr_id = f"test-tm-{cls.suffix}"
        cls.student_a_user_id = f"test-u-stu-a-{cls.suffix}"
        cls.student_b_user_id = f"test-u-stu-b-{cls.suffix}"
        cls.student_a_id = f"test-stu-a-{cls.suffix}"
        cls.student_b_id = f"test-stu-b-{cls.suffix}"
        cls.trainer_user_id = f"test-tr-{cls.suffix}"

        cls.created_user_ids = [
            cls.admin_user_id,
            cls.training_mgr_id,
            cls.student_a_user_id,
            cls.student_b_user_id,
            cls.trainer_user_id,
        ]
        cls.created_student_ids = [cls.student_a_id, cls.student_b_id]

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                # 1. Tạo users
                users = [
                    (cls.admin_user_id, f"admin_{cls.suffix}@daotao.edu.vn", "Admin User"),
                    (cls.training_mgr_id, f"tm_{cls.suffix}@daotao.edu.vn", "Training Manager"),
                    (cls.student_a_user_id, f"student_a_{cls.suffix}@daotao.edu.vn", "Student A"),
                    (cls.student_b_user_id, f"student_b_{cls.suffix}@daotao.edu.vn", "Student B"),
                    (cls.trainer_user_id, f"trainer_{cls.suffix}@daotao.edu.vn", "Trainer User"),
                ]
                for uid, email, name in users:
                    cur.execute(
                        "INSERT INTO users (id, email, password_hash, name, created_at, updated_at) VALUES (%s, %s, 'hash', %s, NOW(), NOW())",
                        (uid, email, name),
                    )

                # Gán roles
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-admin', NOW())", (cls.admin_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-training-manager', NOW())", (cls.training_mgr_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_a_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainee', NOW())", (cls.student_b_user_id,))
                cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-trainer', NOW())", (cls.trainer_user_id,))

                # 2. Tạo Program, Class A, Subject
                cls.prog_id = f"prog-{cls.suffix}"
                cur.execute(
                    "INSERT INTO training_programs (id, code, name, created_at, updated_at) VALUES (%s, %s, 'Program 255-2', NOW(), NOW())",
                    (cls.prog_id, f"PRG2_{cls.suffix}"),
                )

                cls.class_a_id = f"cls-a-{cls.suffix}"
                cur.execute(
                    "INSERT INTO classes (id, class_code, program_id, expected_start_date, max_capacity, status, created_at, updated_at) VALUES (%s, %s, %s, CURDATE() - INTERVAL 5 DAY, 30, 'in_progress', NOW(), NOW())",
                    (cls.class_a_id, f"CLA2_{cls.suffix}", cls.prog_id),
                )

                cls.subject_id = f"sub-{cls.suffix}"
                cur.execute(
                    "INSERT INTO subjects (id, code, name, credits, created_at, updated_at) VALUES (%s, %s, 'Subject 255-2', 3, NOW(), NOW())",
                    (cls.subject_id, f"SUB2_{cls.suffix}"),
                )

                # 3. Tạo học viên
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student A', %s, '0981111111', 'studying', NOW(), NOW())",
                    (cls.student_a_id, cls.student_a_user_id, f"STU_A_{cls.suffix}", f"student_a_{cls.suffix}@daotao.edu.vn"),
                )
                cur.execute(
                    "INSERT INTO students (id, user_id, student_code, full_name, email, phone, status, created_at, updated_at) VALUES (%s, %s, %s, 'Student B', %s, '0982222222', 'studying', NOW(), NOW())",
                    (cls.student_b_id, cls.student_b_user_id, f"STU_B_{cls.suffix}", f"student_b_{cls.suffix}@daotao.edu.vn"),
                )

                # Ghi danh học viên A vào Lớp A
                cur.execute(
                    "INSERT INTO class_enrollments (id, class_id, student_id, status, enrolled_at, enrolled_by, created_at, updated_at) VALUES (%s, %s, %s, 'enrolled', CURDATE() - INTERVAL 5 DAY, %s, NOW(), NOW())",
                    (f"enr-a-{cls.suffix}", cls.class_a_id, cls.student_a_id, cls.admin_user_id),
                )

                # 4. Tạo các buổi học kiểm thử
                cls.sched_1_id = f"sch-1-{cls.suffix}"
                cls.sched_2_id = f"sch-2-{cls.suffix}"
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, 'Buổi học số 1', CURDATE(), 'Ca 1', '08:00:00', '10:00:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_1_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )
                cur.execute(
                    """
                    INSERT INTO class_schedules (id, class_id, subject_id, session_number, topic, learning_date, shift, start_time, end_time, status, instructor_id, created_at, updated_at)
                    VALUES (%s, %s, %s, 2, 'Buổi học số 2', CURDATE() + INTERVAL 1 DAY, 'Ca 2', '13:30:00', '15:30:00', 'scheduled', %s, NOW(), NOW())
                    """,
                    (cls.sched_2_id, cls.class_a_id, cls.subject_id, cls.trainer_user_id),
                )

            conn.commit()
        finally:
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM auth_sessions WHERE user_id IN (%s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
                cur.execute("DELETE FROM absence_request_attachments WHERE request_id IN (SELECT id FROM absence_requests WHERE schedule_id IN (%s, %s))", (cls.sched_1_id, cls.sched_2_id))
                cur.execute("DELETE FROM absence_requests WHERE schedule_id IN (%s, %s)", (cls.sched_1_id, cls.sched_2_id))
                cur.execute("DELETE FROM class_schedules WHERE id IN (%s, %s)", (cls.sched_1_id, cls.sched_2_id))
                cur.execute("DELETE FROM class_enrollments WHERE class_id = %s", (cls.class_a_id,))
                cur.execute("DELETE FROM students WHERE id IN (%s, %s)", tuple(cls.created_student_ids))
                cur.execute("DELETE FROM classes WHERE id = %s", (cls.class_a_id,))
                cur.execute("DELETE FROM subjects WHERE id = %s", (cls.subject_id,))
                cur.execute("DELETE FROM training_programs WHERE id = %s", (cls.prog_id,))
                cur.execute("DELETE FROM user_roles WHERE user_id IN (%s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
                cur.execute("DELETE FROM users WHERE id IN (%s, %s, %s, %s, %s)", tuple(cls.created_user_ids))
            conn.commit()
        finally:
            conn.close()

    def _get_auth_header(self, user_id: str, role: str) -> dict[str, str]:
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth_sessions (session_id, user_id, refresh_jti, created_at, last_activity_at, idle_expires_at, absolute_expires_at)
                    VALUES (%s, %s, %s, NOW(), NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR), DATE_ADD(NOW(), INTERVAL 8 HOUR))
                    """,
                    (session_id, user_id, str(uuid.uuid4())),
                )
            conn.commit()
        finally:
            conn.close()

        with app.app_context():
            token = create_access_token(
                identity=user_id,
                additional_claims={"roles": [role], "sid": session_id},
            )
        return {"Authorization": f"Bearer {token}"}

    def test_01_submit_with_valid_image_and_pdf_attachments(self):
        """Học viên gửi đơn kèm file ảnh PNG và tài liệu PDF hợp lệ."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")

        png_data = _create_minimal_png_bytes()
        pdf_data = _create_minimal_pdf_bytes()

        data = {
            "schedule_id": self.sched_1_id,
            "reason": "Em có lịch khám sức khỏe tổng quát có giấy hẹn và đơn thuốc.",
            "attachments": [
                (io.BytesIO(png_data), "giấy_khám_bệnh.png"),
                (io.BytesIO(pdf_data), "xác nhận của viện.pdf"),
            ],
        }

        res = self.client.post(
            "/api/v1/absence-requests",
            data=data,
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res.status_code, 201)
        res_data = res.get_json()["data"]

        self.assertEqual(len(res_data["attachments"]), 2)
        att1 = res_data["attachments"][0]
        att2 = res_data["attachments"][1]

        self.assertEqual(att1["file_name"], "giấy_khám_bệnh.png")
        self.assertEqual(att1["mime_type"], "image/png")
        self.assertEqual(att2["file_name"], "xác nhận của viện.pdf")
        self.assertEqual(att2["mime_type"], "application/pdf")

        # Lưu lại id để kiểm thử tải file
        self.__class__.created_request_id = res_data["id"]
        self.__class__.created_att_png_id = att1["id"]
        self.__class__.created_att_pdf_id = att2["id"]

    def test_02_download_attachment_authorized_users(self):
        """Kiểm tra quyền tải tệp: Học viên chủ đơn, Giảng viên phụ trách, Quản lý đào tạo."""
        req_id = self.__class__.created_request_id
        att_png_id = self.__class__.created_att_png_id
        att_pdf_id = self.__class__.created_att_pdf_id

        # 1. Học viên chủ đơn tải file PNG
        headers_stu = self._get_auth_header(self.student_a_user_id, "trainee")
        res_stu = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/{att_png_id}",
            headers=headers_stu,
        )
        self.assertEqual(res_stu.status_code, 200)
        self.assertEqual(res_stu.mimetype, "image/png")
        self.assertIn("Cache-Control", res_stu.headers)
        self.assertEqual(len(res_stu.data), len(_create_minimal_png_bytes()))

        # 2. Giảng viên phụ trách buổi học tải file PDF
        headers_tr = self._get_auth_header(self.trainer_user_id, "trainer")
        res_tr = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/{att_pdf_id}",
            headers=headers_tr,
        )
        self.assertEqual(res_tr.status_code, 200)
        self.assertEqual(res_tr.mimetype, "application/pdf")

        # 3. Quản lý đào tạo xem file
        headers_tm = self._get_auth_header(self.training_mgr_id, "training_manager")
        res_tm = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/{att_png_id}",
            headers=headers_tm,
        )
        self.assertEqual(res_tm.status_code, 200)

    def test_03_download_attachment_forbidden_and_unauthorized(self):
        """Kiểm tra chặn người ngoài quyền tải file minh chứng."""
        req_id = self.__class__.created_request_id
        att_png_id = self.__class__.created_att_png_id

        # 1. Học viên B (không phải chủ đơn)
        headers_stu_b = self._get_auth_header(self.student_b_user_id, "trainee")
        res_b = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/{att_png_id}",
            headers=headers_stu_b,
        )
        self.assertEqual(res_b.status_code, 403)
        self.assertEqual(res_b.get_json()["code"], "FORBIDDEN_ABSENCE_ACCESS")

        # 2. Không đăng nhập (không có Bearer token)
        res_no_auth = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/{att_png_id}",
        )
        self.assertEqual(res_no_auth.status_code, 401)

        # 3. Tệp hoặc đơn không tồn tại
        headers_stu = self._get_auth_header(self.student_a_user_id, "trainee")
        res_not_found = self.client.get(
            f"/api/v1/absence-requests/{req_id}/attachments/non-existent-attachment-id",
            headers=headers_stu,
        )
        self.assertEqual(res_not_found.status_code, 404)

    def test_04_attachment_validation_rules(self):
        """Kiểm tra các trường hợp validation minh chứng không hợp lệ."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")

        # 1. Tệp vượt quá 5MB
        huge_bytes = b"0" * (5 * 1024 * 1024 + 1024)
        res_huge = self.client.post(
            "/api/v1/absence-requests",
            data={
                "schedule_id": self.sched_2_id,
                "reason": "Em xin nghỉ phép kiểm tra kích thước file.",
                "attachments": [(io.BytesIO(huge_bytes), "huge_file.pdf")],
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res_huge.status_code, 400)
        self.assertEqual(res_huge.get_json()["code"], "ATTACHMENT_TOO_LARGE")

        # 2. Định dạng bị cấm (.exe, .html, .svg)
        res_exe = self.client.post(
            "/api/v1/absence-requests",
            data={
                "schedule_id": self.sched_2_id,
                "reason": "Em xin nghỉ phép kiểm tra định dạng cấm.",
                "attachments": [(io.BytesIO(b"malicious executable"), "virus.exe")],
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res_exe.status_code, 400)
        self.assertEqual(res_exe.get_json()["code"], "INVALID_ATTACHMENT_TYPE")

        # 3. Giả mạo phần mở rộng: tên .jpg nhưng nội dung là HTML script
        fake_jpg_content = b"<html><script>alert('xss')</script></html>"
        res_fake = self.client.post(
            "/api/v1/absence-requests",
            data={
                "schedule_id": self.sched_2_id,
                "reason": "Em xin nghỉ phép kiểm tra chữ ký ảnh giả mạo.",
                "attachments": [(io.BytesIO(fake_jpg_content), "fake_photo.jpg")],
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res_fake.status_code, 400)
        self.assertEqual(res_fake.get_json()["code"], "INVALID_ATTACHMENT_CONTENT")

        # 4. Hơn 5 tệp đính kèm
        png_data = _create_minimal_png_bytes()
        res_too_many = self.client.post(
            "/api/v1/absence-requests",
            data={
                "schedule_id": self.sched_2_id,
                "reason": "Em xin nghỉ phép gửi quá nhiều file.",
                "attachments": [
                    (io.BytesIO(png_data), f"img_{i}.png") for i in range(6)
                ],
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res_too_many.status_code, 400)
        self.assertEqual(res_too_many.get_json()["code"], "TOO_MANY_ATTACHMENTS")

    def test_05_no_orphan_files_on_failure(self):
        """Kiểm tra cơ chế dọn dẹp chống tệp mồ côi khi tạo đơn thất bại."""
        headers = self._get_auth_header(self.student_a_user_id, "trainee")
        upload_folder = Path(ATTACHMENT_UPLOAD_FOLDER).resolve()
        files_before = set(upload_folder.glob("*")) if upload_folder.exists() else set()

        png_data = _create_minimal_png_bytes()

        # Cố tình gửi duplicate pending trên sched_1_id (đã có đơn ở test 01)
        res = self.client.post(
            "/api/v1/absence-requests",
            data={
                "schedule_id": self.sched_1_id,
                "reason": "Cố tình gửi trùng đơn để kiểm tra tệp mồ côi.",
                "attachments": [(io.BytesIO(png_data), "orphan_test.png")],
            },
            content_type="multipart/form-data",
            headers=headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()["code"], "DUPLICATE_PENDING_REQUEST")

        # Kiểm tra thư mục upload không có thêm bất kỳ tệp mồ côi nào mới
        files_after = set(upload_folder.glob("*")) if upload_folder.exists() else set()
        new_files = files_after - files_before
        self.assertEqual(len(new_files), 0, f"Phát hiện tệp mồ côi chưa được dọn dẹp: {new_files}")


if __name__ == "__main__":
    unittest.main()
