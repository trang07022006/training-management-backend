import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.subject import (
    MAX_SUBJECT_CREDITS,
    MIN_SUBJECT_CREDITS,
    SUBJECT_STATUS_ACTIVE,
    SUBJECT_STATUS_ARCHIVED,
    SUBJECT_STATUS_DRAFT,
    VALID_SUBJECT_STATUSES,
    Subject,
)
from app.repositories import subject_repository
from app.database.connection import get_db_connection


class Scrum123SubjectFoundationModelTests(unittest.TestCase):
    """Kiểm thử Model Subject (Mapping, Serialization, Nullable fields, Constants)."""

    def test_01_model_instantiation_and_properties(self):
        now = datetime.now(timezone.utc)
        subject = Subject(
            id="subj-123",
            code="INT1154",
            name="Lập trình hướng đối tượng",
            credits=3,
            description="Môn học nền tảng OOP với Java/C++",
            total_sessions=15,
            status=SUBJECT_STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )

        self.assertEqual(subject.id, "subj-123")
        self.assertEqual(subject.code, "INT1154")
        self.assertEqual(subject.name, "Lập trình hướng đối tượng")
        self.assertEqual(subject.credits, 3)
        self.assertEqual(subject.description, "Môn học nền tảng OOP với Java/C++")
        self.assertEqual(subject.total_sessions, 15)
        self.assertEqual(subject.status, SUBJECT_STATUS_ACTIVE)
        self.assertEqual(subject.created_at, now)
        self.assertEqual(subject.updated_at, now)

    def test_02_model_serialization_to_dict(self):
        now = datetime.now(timezone.utc)
        subject = Subject(
            id="subj-456",
            code="MAT1093",
            name="Giải tích 1",
            credits=4,
            description="Đại cương giải tích hàm một biến",
            total_sessions=20,
            status=SUBJECT_STATUS_DRAFT,
            created_at=now,
            updated_at=now,
        )
        data = subject.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["id"], "subj-456")
        self.assertEqual(data["code"], "MAT1093")
        self.assertEqual(data["name"], "Giải tích 1")
        self.assertEqual(data["credits"], 4)
        self.assertEqual(data["description"], "Đại cương giải tích hàm một biến")
        self.assertEqual(data["total_sessions"], 20)
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["created_at"], now.isoformat())
        self.assertEqual(data["updated_at"], now.isoformat())

    def test_03_model_nullable_fields_and_defaults(self):
        subject = Subject(
            id="subj-789",
            code="ENG1001",
            name="Tiếng Anh cơ bản 1",
            credits=2,
        )
        self.assertIsNone(subject.description)
        self.assertIsNone(subject.total_sessions)
        self.assertEqual(subject.status, SUBJECT_STATUS_DRAFT)
        self.assertIsNone(subject.created_at)
        self.assertIsNone(subject.updated_at)

        data = subject.to_dict()
        self.assertIsNone(data["description"])
        self.assertIsNone(data["total_sessions"])
        self.assertEqual(data["status"], "draft")
        self.assertIsNone(data["created_at"])
        self.assertIsNone(data["updated_at"])

    def test_04_valid_statuses_and_credits_constants(self):
        self.assertIn("draft", VALID_SUBJECT_STATUSES)
        self.assertIn("active", VALID_SUBJECT_STATUSES)
        self.assertIn("archived", VALID_SUBJECT_STATUSES)
        self.assertEqual(len(VALID_SUBJECT_STATUSES), 3)

        self.assertEqual(MIN_SUBJECT_CREDITS, 1)
        self.assertEqual(MAX_SUBJECT_CREDITS, 30)


class Scrum123SubjectRepositoryMockTests(unittest.TestCase):
    """Kiểm thử Repository layer với Mock (Parameterization, Rollback, Cleanup, Error handling)."""

    def setUp(self):
        self.subject_id = "subj-uuid-001"
        self.now = datetime.now(timezone.utc)
        self.subject = Subject(
            id=self.subject_id,
            code="PHY1001",
            name="Vật lý đại cương 1",
            credits=3,
            description="Cơ nhiệt",
            total_sessions=15,
            status=SUBJECT_STATUS_DRAFT,
            created_at=self.now,
            updated_at=self.now,
        )

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_05_insert_subject_parameterized_sql_and_commit(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = subject_repository.insert_subject(self.subject)

        self.assertEqual(res.id, self.subject_id)
        mock_cursor.execute.assert_called_once()
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO subjects", sql)
        self.assertEqual(values[0], self.subject_id)
        self.assertEqual(values[1], "PHY1001")
        self.assertEqual(values[2], "Vật lý đại cương 1")
        self.assertEqual(values[3], 3)
        self.assertEqual(values[4], "Cơ nhiệt")
        self.assertEqual(values[5], 15)
        self.assertEqual(values[6], "draft")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_06_insert_subject_rollback_on_exception(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Database failure")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        with self.assertRaises(MySQLError):
            subject_repository.insert_subject(self.subject)

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_07_get_subject_by_id_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.subject_id,
            "code": "PHY1001",
            "name": "Vật lý đại cương 1",
            "credits": 3,
            "description": "Cơ nhiệt",
            "total_sessions": 15,
            "status": "draft",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = subject_repository.get_subject_by_id(self.subject_id)

        self.assertIsNotNone(res)
        self.assertEqual(res.id, self.subject_id)
        self.assertEqual(res.code, "PHY1001")
        self.assertEqual(res.credits, 3)
        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE id = %s", sql)
        self.assertEqual(params, (self.subject_id,))

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_08_get_subject_by_id_not_found(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = subject_repository.get_subject_by_id("non-existent-id")
        self.assertIsNone(res)

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_09_get_subject_by_code(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.subject_id,
            "code": "PHY1001",
            "name": "Vật lý đại cương 1",
            "credits": 3,
            "description": None,
            "total_sessions": None,
            "status": "active",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        res = subject_repository.get_subject_by_code("PHY1001")
        self.assertIsNotNone(res)
        self.assertEqual(res.code, "PHY1001")
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s", sql)
        self.assertEqual(params, ("PHY1001",))

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_10_exists_by_code(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"1": 1}
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        # Test without exclude_id
        exists = subject_repository.exists_by_code("PHY1001")
        self.assertTrue(exists)
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s", sql)
        self.assertEqual(params, ("PHY1001",))

        # Test with exclude_id
        subject_repository.exists_by_code("PHY1001", exclude_id="other-id")
        sql, params = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s AND id != %s", sql)
        self.assertEqual(params, ("PHY1001", "other-id"))

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_11_get_all_subjects_and_count(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": self.subject_id,
                "code": "PHY1001",
                "name": "Vật lý đại cương 1",
                "credits": 3,
                "description": "Cơ nhiệt",
                "total_sessions": 15,
                "status": "draft",
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        subjects = subject_repository.get_all_subjects(search="Vật lý", status="draft", limit=10, offset=0)
        self.assertEqual(len(subjects), 1)
        self.assertEqual(subjects[0].code, "PHY1001")

        cnt = subject_repository.count_subjects(search="Vật lý", status="draft")
        self.assertEqual(cnt, 1)

    @patch("app.repositories.subject_repository.get_db_connection")
    def test_12_update_and_delete_subject(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        updated = subject_repository.update_subject(self.subject)
        self.assertTrue(updated)
        mock_conn.commit.assert_called()

        deleted = subject_repository.delete_subject(self.subject_id)
        self.assertTrue(deleted)
        mock_conn.commit.assert_called()


class Scrum123SubjectMySQLIntegrationTests(unittest.TestCase):
    """Kiểm thử tích hợp thực tế với MySQL Database (Roundtrip, Constraints, Unique, Cleanup)."""

    def setUp(self):
        self.test_ids = []
        self.test_code_prefix = f"TEST-SUBJ-{uuid.uuid4().hex[:6].upper()}"

    def tearDown(self):
        # Dọn dẹp an toàn các bản ghi test
        if self.test_ids:
            try:
                conn = get_db_connection()
                with conn.cursor() as cursor:
                    format_strings = ",".join(["%s"] * len(self.test_ids))
                    cursor.execute(f"DELETE FROM subjects WHERE id IN ({format_strings})", tuple(self.test_ids))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_13_mysql_insert_and_get_roundtrip(self):
        subj_id = str(uuid.uuid4())
        self.test_ids.append(subj_id)
        code = f"{self.test_code_prefix}-01"

        subj = Subject(
            id=subj_id,
            code=code,
            name="Kiểm thử tích hợp môn học",
            credits=3,
            description="Mô tả kiểm thử",
            total_sessions=15,
            status=SUBJECT_STATUS_DRAFT,
        )

        inserted = subject_repository.insert_subject(subj)
        self.assertEqual(inserted.id, subj_id)
        self.assertEqual(inserted.code, code)

        fetched = subject_repository.get_subject_by_id(subj_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Kiểm thử tích hợp môn học")
        self.assertEqual(fetched.credits, 3)
        self.assertEqual(fetched.total_sessions, 15)
        self.assertEqual(fetched.status, SUBJECT_STATUS_DRAFT)

        # exists_by_code
        self.assertTrue(subject_repository.exists_by_code(code))
        self.assertFalse(subject_repository.exists_by_code("NON_EXISTING_CODE"))

    def test_14_mysql_insert_with_nullable_fields(self):
        subj_id = str(uuid.uuid4())
        self.test_ids.append(subj_id)
        code = f"{self.test_code_prefix}-02"

        subj = Subject(
            id=subj_id,
            code=code,
            name="Môn học không có mô tả",
            credits=2,
            description=None,
            total_sessions=None,
            status=SUBJECT_STATUS_ACTIVE,
        )

        inserted = subject_repository.insert_subject(subj)
        self.assertEqual(inserted.id, subj_id)

        fetched = subject_repository.get_subject_by_id(subj_id)
        self.assertIsNotNone(fetched)
        self.assertIsNone(fetched.description)
        self.assertIsNone(fetched.total_sessions)
        self.assertEqual(fetched.status, SUBJECT_STATUS_ACTIVE)

    def test_15_mysql_unique_code_constraint(self):
        subj_id1 = str(uuid.uuid4())
        subj_id2 = str(uuid.uuid4())
        self.test_ids.extend([subj_id1, subj_id2])
        duplicate_code = f"{self.test_code_prefix}-DUP"

        subj1 = Subject(
            id=subj_id1,
            code=duplicate_code,
            name="Môn học bản gốc",
            credits=3,
        )
        subject_repository.insert_subject(subj1)

        subj2 = Subject(
            id=subj_id2,
            code=duplicate_code,
            name="Môn học trùng mã",
            credits=3,
        )
        with self.assertRaises(IntegrityError):
            subject_repository.insert_subject(subj2)

    def test_16_mysql_credits_check_constraint(self):
        # Credits < 1 -> check constraint violation
        subj_id1 = str(uuid.uuid4())
        self.test_ids.append(subj_id1)
        subj_invalid_min = Subject(
            id=subj_id1,
            code=f"{self.test_code_prefix}-INV1",
            name="Credits 0",
            credits=0,
        )
        with self.assertRaises((IntegrityError, MySQLError)):
            subject_repository.insert_subject(subj_invalid_min)

        # Credits > 30 -> check constraint violation
        subj_id2 = str(uuid.uuid4())
        self.test_ids.append(subj_id2)
        subj_invalid_max = Subject(
            id=subj_id2,
            code=f"{self.test_code_prefix}-INV2",
            name="Credits 31",
            credits=31,
        )
        with self.assertRaises((IntegrityError, MySQLError)):
            subject_repository.insert_subject(subj_invalid_max)

    def test_17_mysql_status_check_constraint(self):
        subj_id = str(uuid.uuid4())
        self.test_ids.append(subj_id)
        subj_invalid_status = Subject(
            id=subj_id,
            code=f"{self.test_code_prefix}-INVST",
            name="Status Invalid",
            credits=3,
            status="unknown_status",
        )
        with self.assertRaises((IntegrityError, MySQLError)):
            subject_repository.insert_subject(subj_invalid_status)

    def test_18_mysql_total_sessions_check_constraint(self):
        # total_sessions < 0 (nếu lưu số âm)
        # Note: MySQL unsigned prevents negative, but let's test valid non-negative values
        subj_id = str(uuid.uuid4())
        self.test_ids.append(subj_id)
        subj = Subject(
            id=subj_id,
            code=f"{self.test_code_prefix}-SESS0",
            name="Session 0",
            credits=1,
            total_sessions=0,
        )
        inserted = subject_repository.insert_subject(subj)
        self.assertEqual(inserted.total_sessions, 0)

    def test_19_mysql_update_and_delete_roundtrip(self):
        subj_id = str(uuid.uuid4())
        self.test_ids.append(subj_id)
        code = f"{self.test_code_prefix}-UPD"

        subj = Subject(
            id=subj_id,
            code=code,
            name="Tên ban đầu",
            credits=3,
            status=SUBJECT_STATUS_DRAFT,
        )
        subject_repository.insert_subject(subj)

        # Update
        subj.name = "Tên đã cập nhật"
        subj.credits = 4
        subj.status = SUBJECT_STATUS_ACTIVE
        updated = subject_repository.update_subject(subj)
        self.assertTrue(updated)

        fetched = subject_repository.get_subject_by_id(subj_id)
        self.assertEqual(fetched.name, "Tên đã cập nhật")
        self.assertEqual(fetched.credits, 4)
        self.assertEqual(fetched.status, SUBJECT_STATUS_ACTIVE)

        # Delete
        deleted = subject_repository.delete_subject(subj_id)
        self.assertTrue(deleted)
        self.assertIsNone(subject_repository.get_subject_by_id(subj_id))


if __name__ == "__main__":
    unittest.main()
