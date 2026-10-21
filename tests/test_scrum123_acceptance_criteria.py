"""
Bộ kiểm thử chấp nhận (Acceptance Criteria) cho SCRUM-123 - Quản lý môn học (Subject Management).
Tuân thủ toàn bộ các nguyên tắc:
1. Tạo môn học với đầy đủ mã, tên, số buổi, trọng số (weight), mô tả chuẩn đầu ra (learning_outcomes).
2. Cập nhật trọng số (weight).
3. Cập nhật mô tả chuẩn đầu ra (learning_outcomes).
4. GET API trả về đầy đủ các trường mới.
5. Unique code: Từ chối tạo trùng mã môn học (409 DUPLICATE_CODE).
6. Tái sử dụng một môn học ở nhiều chương trình đào tạo (cùng subject_id, không duplicate).
7. Xóa an toàn môn học chưa có dữ liệu phụ thuộc (QA-S123-DELETE).
8. Quy tắc xóa khi môn học có phụ thuộc (chặn 409). Entity lớp học chưa tồn tại được ghi nhận rõ.
9. Bảo vệ dữ liệu live: Tuyệt đối không xóa/sửa LIVE-S1-b45466b9.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.config.jwt_handlers import register_jwt_handlers
from app.database.connection import get_db_connection
from app.models.login_session import LoginSession
from app.models.program_subject import ProgramSubject
from app.models.subject import Subject
from app.models.training_program import TrainingProgram
from app.repositories import program_subject_repository, subject_repository, training_program_repository
from app.routes.program_subject_routes import program_subject_bp
from app.routes.subject_routes import subject_bp
from app.routes.training_program_routes import training_program_bp
from app.services import subject_service
from app.services.subject_service import (
    DuplicateSubjectCodeError,
    SubjectInUseError,
    SubjectNotFoundError,
)


class Scrum123AcceptanceCriteriaTests(unittest.TestCase):
    """Bộ test chấp nhận các tiêu chuẩn của SCRUM-123."""

    @classmethod
    def setUpClass(cls):
        # Dọn dẹp dữ liệu test cũ bắt đầu bằng QA-S123- nếu còn sót lại
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM subjects WHERE code LIKE 'QA-S123-%'")
        test_subjs = cursor.fetchall()
        for s in test_subjs:
            s_id = s["id"]
            cursor.execute("DELETE FROM program_subjects WHERE subject_id = %s", (s_id,))
            cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (s_id,))
            cursor.execute("DELETE FROM subjects WHERE id = %s", (s_id,))
        cursor.execute("DELETE FROM training_programs WHERE code LIKE 'QA-PROG-123-%'")
        conn.commit()
        conn.close()

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="test-secret-key-scrum123-acceptance-criteria",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=15),
            SESSION_IDLE_TIMEOUT=timedelta(minutes=30),
        )
        self.jwt = JWTManager(self.app)
        register_jwt_handlers(self.jwt)
        self.app.register_blueprint(subject_bp)
        self.app.register_blueprint(training_program_bp)
        self.app.register_blueprint(program_subject_bp)

        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)

        self.manager_user_id = "user-course-manage-uuid"
        self.manager_session = LoginSession(
            session_id="session-manager-123",
            user_id=self.manager_user_id,
            refresh_jti="ref-manager-123",
            created_at=self.now,
            last_activity_at=self.now,
            idle_expires_at=self.now + timedelta(minutes=30),
            absolute_expires_at=self.now + timedelta(hours=8),
        )

        with self.app.app_context():
            self.manager_token = create_access_token(
                identity=self.manager_user_id,
                additional_claims={"sid": "session-manager-123"},
            )
        self.auth_headers = {"Authorization": f"Bearer {self.manager_token}"}

        self.patch_sess = patch("app.utils.rbac_auth.get_session_by_id")
        self.mock_get_sess = self.patch_sess.start()
        self.mock_get_sess.return_value = self.manager_session

        self.patch_perm = patch("app.utils.rbac_auth.has_permission")
        self.mock_has_perm = self.patch_perm.start()
        self.mock_has_perm.return_value = True

    def tearDown(self):
        self.patch_sess.stop()
        self.patch_perm.stop()
        # Dọn dẹp chỉ các môn học QA-S123- (TUYỆT ĐỐI không đụng dữ liệu LIVE)
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM subjects WHERE code LIKE 'QA-S123-%'")
        test_subjs = cursor.fetchall()
        for s in test_subjs:
            s_id = s["id"]
            cursor.execute("DELETE FROM program_subjects WHERE subject_id = %s", (s_id,))
            cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (s_id,))
            cursor.execute("DELETE FROM subjects WHERE id = %s", (s_id,))
        cursor.execute("DELETE FROM training_programs WHERE code LIKE 'QA-PROG-123-%'")
        conn.commit()
        conn.close()

    def test_01_create_subject_with_weight_and_learning_outcomes(self):
        """AC1: Tạo môn học với đầy đủ mã, tên, số buổi, trọng số, chuẩn đầu ra."""
        payload = {
            "code": "QA-S123-01",
            "name": "Kiểm thử SCRUM-123",
            "credits": 3,
            "total_sessions": 10,
            "weight": 1.5,
            "learning_outcomes": "Người học đạt được các chuẩn đầu ra được xác định cho môn kiểm thử SCRUM-123.",
            "description": "Mô tả tổng quan môn kiểm thử",
            "status": "active",
        }

        res = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()["data"]

        self.assertEqual(data["code"], "QA-S123-01")
        self.assertEqual(data["name"], "Kiểm thử SCRUM-123")
        self.assertEqual(data["credits"], 3)
        self.assertEqual(data["total_sessions"], 10)
        self.assertEqual(data["weight"], 1.5)
        self.assertEqual(data["learning_outcomes"], payload["learning_outcomes"])
        self.assertEqual(data["status"], "active")

    def test_02_get_subject_returns_all_fields(self):
        """AC2: API GET trả về đầy đủ các trường mới (weight, learning_outcomes)."""
        payload = {
            "code": "QA-S123-GET",
            "name": "Môn học kiểm thử GET",
            "credits": 2,
            "total_sessions": 12,
            "weight": 2.0,
            "learning_outcomes": "Chuẩn đầu ra môn GET",
            "status": "draft",
        }
        res_create = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        self.assertEqual(res_create.status_code, 201)
        created_id = res_create.get_json()["data"]["id"]

        # 1. GET chi tiết
        res_get = self.client.get(f"/api/v1/subjects/{created_id}", headers=self.auth_headers)
        self.assertEqual(res_get.status_code, 200)
        detail = res_get.get_json()["data"]
        self.assertEqual(detail["weight"], 2.0)
        self.assertEqual(detail["learning_outcomes"], "Chuẩn đầu ra môn GET")

        # 2. GET danh sách
        res_list = self.client.get("/api/v1/subjects?search=QA-S123-GET", headers=self.auth_headers)
        self.assertEqual(res_list.status_code, 200)
        items = res_list.get_json()["data"]["items"]
        self.assertTrue(any(i["id"] == created_id and i["weight"] == 2.0 for i in items))

    def test_03_update_weight_and_learning_outcomes_put(self):
        """AC3: Cập nhật weight và learning_outcomes qua PUT."""
        payload = {
            "code": "QA-S123-PUT",
            "name": "Môn học trước khi PUT",
            "credits": 3,
            "total_sessions": 15,
            "weight": 1.0,
            "learning_outcomes": "Chuẩn đầu ra ban đầu",
        }
        res_create = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        created_id = res_create.get_json()["data"]["id"]

        update_payload = {
            "code": "QA-S123-PUT",
            "name": "Môn học sau khi PUT",
            "credits": 3,
            "total_sessions": 20,
            "weight": 2.5,
            "learning_outcomes": "Chuẩn đầu ra đã được cập nhật qua PUT",
            "status": "active",
        }
        res_put = self.client.put(f"/api/v1/subjects/{created_id}", json=update_payload, headers=self.auth_headers)
        self.assertEqual(res_put.status_code, 200)
        updated = res_put.get_json()["data"]
        self.assertEqual(updated["weight"], 2.5)
        self.assertEqual(updated["learning_outcomes"], "Chuẩn đầu ra đã được cập nhật qua PUT")
        self.assertEqual(updated["total_sessions"], 20)

    def test_04_update_weight_and_learning_outcomes_patch(self):
        """AC4: Cập nhật từng phần (PATCH) weight và learning_outcomes."""
        payload = {
            "code": "QA-S123-PATCH",
            "name": "Môn học PATCH",
            "credits": 4,
            "total_sessions": 30,
            "weight": 1.5,
            "learning_outcomes": "Ban đầu",
        }
        res_create = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        created_id = res_create.get_json()["data"]["id"]

        # Cập nhật weight riêng
        res_patch1 = self.client.patch(f"/api/v1/subjects/{created_id}", json={"weight": 3.0}, headers=self.auth_headers)
        self.assertEqual(res_patch1.status_code, 200)
        self.assertEqual(res_patch1.get_json()["data"]["weight"], 3.0)
        self.assertEqual(res_patch1.get_json()["data"]["learning_outcomes"], "Ban đầu")

        # Cập nhật learning_outcomes riêng
        res_patch2 = self.client.patch(
            f"/api/v1/subjects/{created_id}",
            json={"learning_outcomes": "Chuẩn đầu ra cập nhật PATCH"},
            headers=self.auth_headers,
        )
        self.assertEqual(res_patch2.status_code, 200)
        self.assertEqual(res_patch2.get_json()["data"]["weight"], 3.0)
        self.assertEqual(res_patch2.get_json()["data"]["learning_outcomes"], "Chuẩn đầu ra cập nhật PATCH")

    def test_05_unique_subject_code(self):
        """AC5: Mã môn học là duy nhất; từ chối khi tạo trùng mã (409 DUPLICATE_CODE)."""
        payload = {
            "code": "QA-S123-UNIQ",
            "name": "Môn học duy nhất",
            "credits": 3,
            "weight": 1.0,
        }
        res1 = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        self.assertEqual(res1.status_code, 201)

        res2 = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        self.assertEqual(res2.status_code, 409)
        body = res2.get_json()
        self.assertEqual(body["code"], "DUPLICATE_CODE")
        self.assertIn("tồn tại", body["message"])

    def test_06_subject_reuse_across_multiple_programs(self):
        """AC6: Một môn học dùng lại được ở nhiều chương trình đào tạo (cùng subject_id)."""
        # 1. Tạo 1 môn học
        subj_payload = {
            "code": "QA-S123-MULTI",
            "name": "Môn học dùng chung nhiều CTĐT",
            "credits": 3,
            "total_sessions": 30,
            "weight": 2.0,
            "learning_outcomes": "Mục tiêu dùng chung",
        }
        res_subj = self.client.post("/api/v1/subjects", json=subj_payload, headers=self.auth_headers)
        self.assertEqual(res_subj.status_code, 201)
        subj_id = res_subj.get_json()["data"]["id"]

        # 2. Tạo 2 chương trình đào tạo
        prog_a = TrainingProgram(
            id=str(uuid.uuid4()),
            code="QA-PROG-123-A",
            name="Chương trình Đào tạo A",
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        prog_b = TrainingProgram(
            id=str(uuid.uuid4()),
            code="QA-PROG-123-B",
            name="Chương trình Đào tạo B",
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        training_program_repository.insert_training_program(prog_a)
        training_program_repository.insert_training_program(prog_b)

        # 3. Gắn CHÍNH subject đó vào Chương trình A
        ps_a = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=prog_a.id,
            subject_id=subj_id,
            semester=1,
            is_mandatory=True,
            order_index=1,
            created_at=self.now,
            updated_at=self.now,
        )
        inserted_a = program_subject_repository.insert_program_subject_ordered(ps_a)
        self.assertIsNotNone(inserted_a)

        # 4. Gắn CHÍNH subject đó vào Chương trình B
        ps_b = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=prog_b.id,
            subject_id=subj_id,
            semester=2,
            is_mandatory=False,
            order_index=1,
            created_at=self.now,
            updated_at=self.now,
        )
        inserted_b = program_subject_repository.insert_program_subject_ordered(ps_b)
        self.assertIsNotNone(inserted_b)

        # 5. Xác minh: Cùng subject_id, không nhân bản môn học
        subjects_for_a = program_subject_repository.get_program_structure(prog_a.id)
        subjects_for_b = program_subject_repository.get_program_structure(prog_b.id)

        self.assertEqual(len(subjects_for_a), 1)
        self.assertEqual(len(subjects_for_b), 1)
        self.assertEqual(subjects_for_a[0].subject_id, subj_id)
        self.assertEqual(subjects_for_b[0].subject_id, subj_id)
        self.assertEqual(subjects_for_a[0].subject_id, subjects_for_b[0].subject_id)

    def test_07_delete_unused_subject_success(self):
        """AC7: Xóa môn học chưa có ràng buộc (QA-S123-DELETE) phải thành công."""
        payload = {
            "code": "QA-S123-DELETE",
            "name": "Môn học để test xóa",
            "credits": 2,
            "weight": 1.0,
        }
        res_create = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        self.assertEqual(res_create.status_code, 201)
        del_id = res_create.get_json()["data"]["id"]

        # Xóa
        res_del = self.client.delete(f"/api/v1/subjects/{del_id}", headers=self.auth_headers)
        self.assertEqual(res_del.status_code, 200)

        # Reload: không còn
        res_check = self.client.get(f"/api/v1/subjects/{del_id}", headers=self.auth_headers)
        self.assertEqual(res_check.status_code, 404)

    def test_08_delete_subject_in_use_blocked(self):
        """AC8: Xóa môn học đang có dữ liệu liên kết bị chặn (409 SUBJECT_IN_USE)."""
        # Tạo môn học
        payload = {
            "code": "QA-S123-INUSE",
            "name": "Môn học có phụ thuộc",
            "credits": 3,
            "weight": 1.5,
        }
        res_create = self.client.post("/api/v1/subjects", json=payload, headers=self.auth_headers)
        subj_id = res_create.get_json()["data"]["id"]

        # Gắn vào chương trình đào tạo
        prog = TrainingProgram(
            id=str(uuid.uuid4()),
            code="QA-PROG-123-USE",
            name="Chương trình Test Khóa Xóa",
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )
        training_program_repository.insert_training_program(prog)

        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=prog.id,
            subject_id=subj_id,
            semester=1,
            is_mandatory=True,
            order_index=1,
            created_at=self.now,
            updated_at=self.now,
        )
        program_subject_repository.insert_program_subject_ordered(ps)

        # Thử xóa môn học -> Phải bị chặn 409
        res_del = self.client.delete(f"/api/v1/subjects/{subj_id}", headers=self.auth_headers)
        self.assertEqual(res_del.status_code, 409)
        body = res_del.get_json()
        self.assertEqual(body["code"], "SUBJECT_IN_USE")

        # Xác minh môn học vẫn tồn tại nguyên vẹn
        res_get = self.client.get(f"/api/v1/subjects/{subj_id}", headers=self.auth_headers)
        self.assertEqual(res_get.status_code, 200)

    def test_09_preserve_live_subject(self):
        """AC9: Đảm bảo dữ liệu LIVE (LIVE-S1-b45466b9) được giữ nguyên vẹn."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, code, name, credits FROM subjects WHERE code = 'LIVE-S1-b45466b9'")
        live_subj = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(live_subj, "Môn học LIVE-S1-b45466b9 phải tồn tại và không bị xóa.")
        self.assertEqual(live_subj["code"], "LIVE-S1-b45466b9")


if __name__ == "__main__":
    unittest.main()
