import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import Error as MySQLError, IntegrityError

from app.models.training_program import (
    PROGRAM_STATUS_ACTIVE,
    PROGRAM_STATUS_ARCHIVED,
    PROGRAM_STATUS_DRAFT,
    VALID_PROGRAM_STATUSES,
    TrainingProgram,
)
from app.repositories import training_program_repository
from app.database.connection import get_db_connection


class Scrum122ProgramFoundationModelTests(unittest.TestCase):
    """Kiểm thử Model TrainingProgram (Mapping, Serialization, Nullable fields)."""

    def test_01_model_instantiation_and_properties(self):
        now = datetime.now(timezone.utc)
        program = TrainingProgram(
            id="prog-123",
            code="CNTT-2026",
            name="Công nghệ Thông tin 2026",
            description="Chương trình đào tạo Cử nhân CNTT",
            duration_semesters=8,
            status=PROGRAM_STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )

        self.assertEqual(program.id, "prog-123")
        self.assertEqual(program.code, "CNTT-2026")
        self.assertEqual(program.name, "Công nghệ Thông tin 2026")
        self.assertEqual(program.description, "Chương trình đào tạo Cử nhân CNTT")
        self.assertEqual(program.duration_semesters, 8)
        self.assertEqual(program.status, PROGRAM_STATUS_ACTIVE)
        self.assertEqual(program.created_at, now)
        self.assertEqual(program.updated_at, now)

    def test_02_model_serialization_to_dict(self):
        now = datetime.now(timezone.utc)
        program = TrainingProgram(
            id="prog-456",
            code="KTPM-2026",
            name="Kỹ thuật Phần mềm",
            description="Chương trình kỹ sư phần mềm",
            duration_semesters=9,
            status=PROGRAM_STATUS_DRAFT,
            created_at=now,
            updated_at=now,
        )
        data = program.to_dict()

        self.assertIsInstance(data, dict)
        self.assertEqual(data["id"], "prog-456")
        self.assertEqual(data["code"], "KTPM-2026")
        self.assertEqual(data["name"], "Kỹ thuật Phần mềm")
        self.assertEqual(data["description"], "Chương trình kỹ sư phần mềm")
        self.assertEqual(data["duration_semesters"], 9)
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["created_at"], now.isoformat())
        self.assertEqual(data["updated_at"], now.isoformat())

    def test_03_model_nullable_fields_and_defaults(self):
        program = TrainingProgram(
            id="prog-789",
            code="DTVT-2026",
            name="Điện tử Viễn thông",
        )
        self.assertIsNone(program.description)
        self.assertIsNone(program.duration_semesters)
        self.assertEqual(program.status, PROGRAM_STATUS_DRAFT)
        self.assertIsNone(program.created_at)
        self.assertIsNone(program.updated_at)

        data = program.to_dict()
        self.assertIsNone(data["description"])
        self.assertIsNone(data["duration_semesters"])
        self.assertEqual(data["status"], "draft")
        self.assertIsNone(data["created_at"])
        self.assertIsNone(data["updated_at"])

    def test_04_valid_statuses_constant(self):
        self.assertIn("draft", VALID_PROGRAM_STATUSES)
        self.assertIn("active", VALID_PROGRAM_STATUSES)
        self.assertIn("archived", VALID_PROGRAM_STATUSES)
        self.assertEqual(len(VALID_PROGRAM_STATUSES), 3)


class Scrum122ProgramRepositoryMockTests(unittest.TestCase):
    """Kiểm thử Repository layer với Mock (Parameterization, Rollback, Cleanup, Error handling)."""

    def setUp(self):
        self.program_id = "prog-uuid-001"
        self.now = datetime.now(timezone.utc)
        self.program = TrainingProgram(
            id=self.program_id,
            code="AI-2026",
            name="Trí tuệ Nhân tạo",
            description="Chuyên ngành AI",
            duration_semesters=8,
            status="active",
            created_at=self.now,
            updated_at=self.now,
        )

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_05_insert_program_parameterized(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = training_program_repository.insert_training_program(self.program)

        self.assertEqual(result.id, self.program_id)
        mock_cursor.execute.assert_called_once()
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("INSERT INTO training_programs", sql)
        self.assertIn("%s, %s, %s, %s, %s, %s, %s, %s, %s", sql)
        self.assertEqual(values[0], self.program_id)
        self.assertEqual(values[1], "AI-2026")
        self.assertEqual(values[2], "Trí tuệ Nhân tạo")
        self.assertEqual(values[3], "Chuyên ngành AI")
        self.assertEqual(values[4], 8)
        self.assertIsNone(values[5])  # standard_tuition_fee
        self.assertEqual(values[6], "active")

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_06_get_program_by_id(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.program_id,
            "code": "AI-2026",
            "name": "Trí tuệ Nhân tạo",
            "description": "Chuyên ngành AI",
            "duration_semesters": 8,
            "status": "active",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = training_program_repository.get_training_program_by_id(self.program_id)

        self.assertIsNotNone(result)
        self.assertEqual(result.id, self.program_id)
        self.assertEqual(result.code, "AI-2026")
        self.assertEqual(result.name, "Trí tuệ Nhân tạo")
        self.assertEqual(result.duration_semesters, 8)
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE id = %s", sql)
        self.assertEqual(values, (self.program_id,))

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_07_get_program_by_id_not_found_returns_none(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = training_program_repository.get_training_program_by_id("non-existent-id")
        self.assertIsNone(result)

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_08_get_program_by_code(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {
            "id": self.program_id,
            "code": "AI-2026",
            "name": "Trí tuệ Nhân tạo",
            "description": None,
            "duration_semesters": None,
            "status": "draft",
            "created_at": self.now,
            "updated_at": self.now,
        }
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        result = training_program_repository.get_training_program_by_code("AI-2026")
        self.assertIsNotNone(result)
        self.assertEqual(result.code, "AI-2026")
        self.assertIsNone(result.description)
        self.assertIsNone(result.duration_semesters)
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s", sql)
        self.assertEqual(values, ("AI-2026",))

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_09_exists_by_code(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = {"1": 1}
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        self.assertTrue(training_program_repository.exists_by_code("AI-2026"))

        mock_cursor.fetchone.return_value = None
        self.assertFalse(training_program_repository.exists_by_code("UNKNOWN-CODE"))

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_10_exists_by_code_with_exclude_id(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        training_program_repository.exists_by_code("AI-2026", exclude_id="prog-123")
        sql, values = mock_cursor.execute.call_args[0]
        self.assertIn("WHERE code = %s AND id != %s", sql)
        self.assertEqual(values, ("AI-2026", "prog-123"))

    @patch("app.repositories.training_program_repository._database_cursor")
    def test_11_get_all_training_programs_and_count(self, mock_cursor_ctx):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {
                "id": "p1",
                "code": "C1",
                "name": "N1",
                "description": None,
                "duration_semesters": 8,
                "status": "active",
                "created_at": self.now,
                "updated_at": self.now,
            }
        ]
        mock_cursor.fetchone.return_value = {"total": 1}
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        programs = training_program_repository.get_all_training_programs(status="active", limit=10, offset=0)
        self.assertEqual(len(programs), 1)
        self.assertEqual(programs[0].id, "p1")

        count = training_program_repository.count_training_programs(status="active")
        self.assertEqual(count, 1)

    @patch("app.repositories.training_program_repository.get_db_connection")
    def test_12_database_error_handling_and_rollback(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = MySQLError("Database connection dropped")
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        with self.assertRaises(MySQLError):
            training_program_repository.insert_training_program(self.program)

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


class Scrum122ProgramDatabaseIntegrationTests(unittest.TestCase):
    """Kiểm thử trực tiếp trên MySQL Database (Schema, Constraints, Roundtrip, Cleanup)."""

    def setUp(self):
        self.test_id_1 = str(uuid.uuid4())
        self.test_id_2 = str(uuid.uuid4())
        self.test_code_1 = f"TEST-{uuid.uuid4().hex[:8].upper()}"
        self.test_code_2 = f"TEST-{uuid.uuid4().hex[:8].upper()}"

    def tearDown(self):
        # Dọn dẹp dữ liệu test an toàn
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM training_programs WHERE id IN (%s, %s)", (self.test_id_1, self.test_id_2))
        conn.commit()
        cur.close()
        conn.close()

    def test_13_db_insert_and_read_roundtrip(self):
        program = TrainingProgram(
            id=self.test_id_1,
            code=self.test_code_1,
            name="Kiểm thử Chương trình Đào tạo",
            description="Mô tả kiểm thử tích hợp",
            duration_semesters=8,
            status=PROGRAM_STATUS_ACTIVE,
        )

        inserted = training_program_repository.insert_training_program(program)
        self.assertEqual(inserted.id, self.test_id_1)

        fetched = training_program_repository.get_training_program_by_id(self.test_id_1)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, self.test_id_1)
        self.assertEqual(fetched.code, self.test_code_1)
        self.assertEqual(fetched.name, "Kiểm thử Chương trình Đào tạo")
        self.assertEqual(fetched.description, "Mô tả kiểm thử tích hợp")
        self.assertEqual(fetched.duration_semesters, 8)
        self.assertEqual(fetched.status, "active")

        # By code
        by_code = training_program_repository.get_training_program_by_code(self.test_code_1)
        self.assertIsNotNone(by_code)
        self.assertEqual(by_code.id, self.test_id_1)

        # Exists
        self.assertTrue(training_program_repository.exists_by_code(self.test_code_1))
        self.assertFalse(training_program_repository.exists_by_code(self.test_code_1, exclude_id=self.test_id_1))

    def test_14_db_unique_constraint_on_code(self):
        program1 = TrainingProgram(
            id=self.test_id_1,
            code=self.test_code_1,
            name="Chương trình 1",
        )
        training_program_repository.insert_training_program(program1)

        program2 = TrainingProgram(
            id=self.test_id_2,
            code=self.test_code_1,  # Trùng code
            name="Chương trình 2 (Trùng code)",
        )
        with self.assertRaises(IntegrityError):
            training_program_repository.insert_training_program(program2)

    def test_15_db_check_constraint_on_status(self):
        # Trạng thái không hợp lệ: 'deleted' hoặc 'invalid'
        invalid_program = TrainingProgram(
            id=self.test_id_1,
            code=self.test_code_1,
            name="Chương trình trạng thái sai",
            status="invalid_status",
        )
        with self.assertRaises(Exception):
            training_program_repository.insert_training_program(invalid_program)

    def test_16_db_delete_program(self):
        program = TrainingProgram(
            id=self.test_id_1,
            code=self.test_code_1,
            name="Chương trình sẽ bị xóa",
        )
        training_program_repository.insert_training_program(program)
        self.assertTrue(training_program_repository.exists_by_code(self.test_code_1))

        deleted = training_program_repository.delete_training_program(self.test_id_1)
        self.assertTrue(deleted)
        self.assertFalse(training_program_repository.exists_by_code(self.test_code_1))
