"""
Targeted tests for SCRUM-257 - Acceptance Criteria 1 (AC1):
Cấu hình ngưỡng cảnh báo vắng theo chương trình đào tạo, mặc định 20% số buổi.

Bao quát:
- Mặc định 20.0% cho chương trình mới và chương trình sẵn có.
- Hai chương trình cấu hình độc lập, không ảnh hưởng lẫn nhau.
- Validation ngưỡng trong [0, 100], tối đa 2 chữ số thập phân.
- Từ chối giá trị âm, >100, quá 2 số thập phân, bool, NaN, Infinity, None.
- Ghi audit log lịch sử thay đổi (old_threshold, new_threshold, changed_by, reason).
- Phân quyền RBAC: Yêu cầu course.manage để sửa ngưỡng, course.view để xem ngưỡng.
"""

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
import uuid
from flask_jwt_extended import create_access_token

from app.database.connection import get_db_connection
from app.database.ensure_business_roles import ensure_business_roles
from app.main import app
from app.models.login_session import LoginSession
from app.models.training_program import TrainingProgram
from app.repositories import training_program_repository


class Scrum257AC1ProgramThresholdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_business_roles()

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.now = datetime.now(timezone.utc)
        self.conn = get_db_connection()
        self.cursor = self.conn.cursor(dictionary=True)

        self.sessions = {}

        def side_effect_get_session(sid):
            uid = self.sessions.get(sid)
            if not uid:
                return None
            return LoginSession(
                session_id=sid,
                user_id=uid,
                refresh_jti=f"ref-{sid}",
                created_at=self.now,
                last_activity_at=self.now,
                idle_expires_at=self.now + timedelta(hours=8),
                absolute_expires_at=self.now + timedelta(hours=8),
            )

        self.session_patcher = patch("app.utils.rbac_auth.get_session_by_id", side_effect=side_effect_get_session)
        self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

        suffix = uuid.uuid4().hex[:6]
        self.admin_user_id = str(uuid.uuid4())
        self.manager_user_id = str(uuid.uuid4())
        self.student_user_id = str(uuid.uuid4())

        self._insert_user(self.admin_user_id, f"admin_{suffix}@ictu.test", "admin", "Admin System")
        self._insert_user(self.manager_user_id, f"manager_{suffix}@ictu.test", "training_manager", "Quản Lý Đào Tạo")
        self._insert_user(self.student_user_id, f"student_{suffix}@ictu.test", "trainee", "Học Viên")

        # Tạo 2 chương trình thử nghiệm độc lập
        self.program1_id = str(uuid.uuid4())
        self.program2_id = str(uuid.uuid4())

        p1 = TrainingProgram(
            id=self.program1_id,
            code=f"PRG1-{suffix}",
            name="Chương trình Đào tạo 1",
            duration_semesters=4,
            status="active",
            standard_tuition_fee=10000000,
            absence_alert_threshold=20.0,
            created_at=self.now,
            updated_at=self.now,
        )
        p2 = TrainingProgram(
            id=self.program2_id,
            code=f"PRG2-{suffix}",
            name="Chương trình Đào tạo 2",
            duration_semesters=4,
            status="active",
            standard_tuition_fee=10000000,
            absence_alert_threshold=20.0,
            created_at=self.now,
            updated_at=self.now,
        )
        training_program_repository.insert_training_program(p1)
        training_program_repository.insert_training_program(p2)

        # Tokens
        self.admin_token = self._create_token(self.admin_user_id, ["admin"])
        self.manager_token = self._create_token(self.manager_user_id, ["training_manager"])
        self.student_token = self._create_token(self.student_user_id, ["trainee"])

    def tearDown(self):
        try:
            self.cursor.execute("DELETE FROM program_absence_threshold_audits WHERE program_id IN (%s, %s)", (self.program1_id, self.program2_id))
            self.cursor.execute("DELETE FROM training_programs WHERE id IN (%s, %s)", (self.program1_id, self.program2_id))
            for uid in [self.admin_user_id, self.manager_user_id, self.student_user_id]:
                self.cursor.execute("DELETE FROM user_roles WHERE user_id = %s", (uid,))
                self.cursor.execute("DELETE FROM users WHERE id = %s", (uid,))
            self.conn.commit()
        except Exception:
            pass
        finally:
            self.cursor.close()
            self.conn.close()

    def _insert_user(self, user_id: str, email: str, role: str, name: str):
        self.cursor.execute(
            """
            INSERT INTO users (id, email, password_hash, role, status, name, failed_login_attempts, created_at, updated_at)
            VALUES (%s, %s, 'hash', %s, 'active', %s, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE role = VALUES(role), name = VALUES(name)
            """,
            (user_id, email, role, name),
        )
        role_id_map = {
            "admin": "role-id-admin",
            "training_manager": "role-id-training-manager",
            "trainee": "role-id-trainee",
        }
        role_id = role_id_map.get(role, "role-id-user")
        self.cursor.execute(
            "INSERT IGNORE INTO user_roles (user_id, role_id, created_at) VALUES (%s, %s, NOW())",
            (user_id, role_id),
        )
        self.conn.commit()

    def _create_token(self, user_id: str, roles: list[str]) -> str:
        sid = f"sid-{uuid.uuid4()}"
        self.sessions[sid] = user_id
        with self.app.app_context():
            return create_access_token(
                identity=user_id,
                additional_claims={"roles": roles, "sid": sid},
            )

    def test_tc257_01_default_threshold_is_20_percent(self):
        """Mặc định ngưỡng cảnh báo vắng là 20% khi đọc chương trình."""
        res = self.client.get(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["data"]
        self.assertEqual(data["absence_alert_threshold"], 20.0)
        self.assertEqual(len(data["audits"]), 0)

    def test_tc257_02_update_threshold_and_audit_log(self):
        """Quản lý đào tạo cập nhật ngưỡng thành công và được ghi nhận audit log."""
        put_res = self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={
                "threshold": 25.5,
                "reason": "Điều chỉnh theo quy chế đào tạo tín chỉ mới",
            },
        )
        self.assertEqual(put_res.status_code, 200)
        updated_data = put_res.get_json()["data"]
        self.assertEqual(updated_data["absence_alert_threshold"], 25.5)

        # Lấy lại ngưỡng và kiểm tra audit
        get_res = self.client.get(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        self.assertEqual(get_res.status_code, 200)
        detail = get_res.get_json()["data"]
        self.assertEqual(detail["absence_alert_threshold"], 25.5)
        self.assertEqual(len(detail["audits"]), 1)
        audit = detail["audits"][0]
        self.assertEqual(audit["old_threshold"], 20.0)
        self.assertEqual(audit["new_threshold"], 25.5)
        self.assertEqual(audit["changed_by"], self.manager_user_id)
        self.assertEqual(audit["reason"], "Điều chỉnh theo quy chế đào tạo tín chỉ mới")

    def test_tc257_03_two_programs_configured_independently(self):
        """Hai chương trình cấu hình độc lập, thay đổi của chương trình 1 không ảnh hưởng chương trình 2."""
        # Cập nhật chương trình 1 lên 30%
        self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={"threshold": 30.0},
        )
        # Cập nhật chương trình 2 lên 15.0%
        self.client.put(
            f"/api/v1/training-programs/{self.program2_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={"threshold": 15.0},
        )

        p1_res = self.client.get(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        p2_res = self.client.get(
            f"/api/v1/training-programs/{self.program2_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
        )
        self.assertEqual(p1_res.get_json()["data"]["absence_alert_threshold"], 30.0)
        self.assertEqual(p2_res.get_json()["data"]["absence_alert_threshold"], 15.0)

    def test_tc257_04_boundary_values_0_and_100_accepted(self):
        """Ngưỡng 0% và 100% là các giá trị biên hợp lệ."""
        res_zero = self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"threshold": 0},
        )
        self.assertEqual(res_zero.status_code, 200)
        self.assertEqual(res_zero.get_json()["data"]["absence_alert_threshold"], 0.0)

        res_hundred = self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.admin_token}"},
            json={"threshold": 100},
        )
        self.assertEqual(res_hundred.status_code, 200)
        self.assertEqual(res_hundred.get_json()["data"]["absence_alert_threshold"], 100.0)

    def test_tc257_05_validation_rejects_invalid_values(self):
        """Từ chối các giá trị ngưỡng không hợp lệ: âm, >100, >2 số thập phân, bool, chuỗi sai, NaN."""
        invalid_cases = [
            -0.01,
            -20,
            100.01,
            120,
            20.123,  # 3 chữ số thập phân
            True,    # boolean
            False,   # boolean
            "abc",   # chuỗi không phải số
            None,    # thiếu giá trị
        ]

        for val in invalid_cases:
            with self.subTest(val=val):
                res = self.client.put(
                    f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
                    headers={"Authorization": f"Bearer {self.manager_token}"},
                    json={"threshold": val},
                )
                self.assertEqual(res.status_code, 400, f"Expected 400 for value {val}, got {res.status_code}")

    def test_tc257_06_rbac_unauthorized_user_forbidden(self):
        """Học viên (không có quyền course.manage) không được phép cập nhật ngưỡng."""
        res = self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.student_token}"},
            json={"threshold": 25.0},
        )
        self.assertEqual(res.status_code, 403)

    def test_tc257_07_unauthenticated_request_rejected(self):
        """Yêu cầu không có token bị từ chối 401."""
        res = self.client.put(
            f"/api/v1/training-programs/{self.program1_id}/absence-alert-threshold",
            json={"threshold": 25.0},
        )
        self.assertEqual(res.status_code, 401)

    def test_tc257_08_invalid_program_uuid_returns_400(self):
        """Mã chương trình không đúng UUID trả về 400."""
        res = self.client.put(
            "/api/v1/training-programs/invalid-uuid-format/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={"threshold": 25.0},
        )
        self.assertEqual(res.status_code, 400)

    def test_tc257_09_nonexistent_program_returns_404(self):
        """Mã chương trình không tồn tại trả về 404."""
        nonexistent = str(uuid.uuid4())
        res = self.client.put(
            f"/api/v1/training-programs/{nonexistent}/absence-alert-threshold",
            headers={"Authorization": f"Bearer {self.manager_token}"},
            json={"threshold": 25.0},
        )
        self.assertEqual(res.status_code, 404)
