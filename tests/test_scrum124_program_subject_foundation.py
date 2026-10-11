import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from mysql.connector import DatabaseError, Error as MySQLError, IntegrityError

from app.database.connection import get_db_connection
from app.models.program_subject import ProgramSubject
from app.models.program_subject_prerequisite import ProgramSubjectPrerequisite
from app.models.subject import SUBJECT_STATUS_ACTIVE, Subject
from app.models.training_program import PROGRAM_STATUS_ACTIVE, TrainingProgram
from app.repositories import (
    program_subject_repository,
    subject_repository,
    training_program_repository,
)


class Scrum124ProgramSubjectModelTests(unittest.TestCase):
    """Kiểm thử Model ProgramSubject và ProgramSubjectPrerequisite (Dataclass, Serialization, Defaults)."""

    def test_01_program_subject_model_properties_and_defaults(self):
        now = datetime.now(timezone.utc)
        ps = ProgramSubject(
            id="ps-101",
            program_id="prog-101",
            subject_id="subj-101",
            semester=2,
            is_mandatory=True,
            order_index=3,
            created_at=now,
            updated_at=now,
        )

        self.assertEqual(ps.id, "ps-101")
        self.assertEqual(ps.program_id, "prog-101")
        self.assertEqual(ps.subject_id, "subj-101")
        self.assertEqual(ps.semester, 2)
        self.assertTrue(ps.is_mandatory)
        self.assertEqual(ps.order_index, 3)
        self.assertEqual(ps.created_at, now)
        self.assertEqual(ps.updated_at, now)

    def test_02_program_subject_serialization_to_dict(self):
        now = datetime.now(timezone.utc)
        ps = ProgramSubject(
            id="ps-102",
            program_id="prog-101",
            subject_id="subj-102",
            semester=None,  # Nullable semester
            is_mandatory=False,
            order_index=1,
            created_at=now,
            updated_at=now,
            subject_code="CS101",
            subject_name="Khoa học máy tính",
            subject_credits=3,
            subject_status=SUBJECT_STATUS_ACTIVE,
            prerequisites=[{"id": "pr-1", "prerequisite_subject_code": "MATH101"}],
        )

        data = ps.to_dict()
        self.assertEqual(data["id"], "ps-102")
        self.assertEqual(data["program_id"], "prog-101")
        self.assertEqual(data["subject_id"], "subj-102")
        self.assertIsNone(data["semester"])
        self.assertFalse(data["is_mandatory"])
        self.assertEqual(data["order_index"], 1)
        self.assertEqual(data["created_at"], now.isoformat())
        self.assertEqual(data["updated_at"], now.isoformat())
        self.assertEqual(data["subject_code"], "CS101")
        self.assertEqual(data["subject_name"], "Khoa học máy tính")
        self.assertEqual(data["subject_credits"], 3)
        self.assertEqual(data["subject_status"], SUBJECT_STATUS_ACTIVE)
        self.assertEqual(len(data["prerequisites"]), 1)

    def test_03_prerequisite_model_properties_and_serialization(self):
        now = datetime.now(timezone.utc)
        prereq = ProgramSubjectPrerequisite(
            id="pr-201",
            program_id="prog-101",
            program_subject_id="ps-102",
            prerequisite_program_subject_id="ps-101",
            created_at=now,
            prerequisite_subject_code="CS101",
            prerequisite_subject_name="Khoa học máy tính",
        )

        self.assertEqual(prereq.id, "pr-201")
        self.assertEqual(prereq.program_id, "prog-101")
        self.assertEqual(prereq.program_subject_id, "ps-102")
        self.assertEqual(prereq.prerequisite_program_subject_id, "ps-101")
        self.assertEqual(prereq.created_at, now)

        data = prereq.to_dict()
        self.assertEqual(data["id"], "pr-201")
        self.assertEqual(data["program_id"], "prog-101")
        self.assertEqual(data["program_subject_id"], "ps-102")
        self.assertEqual(data["prerequisite_program_subject_id"], "ps-101")
        self.assertEqual(data["created_at"], now.isoformat())
        self.assertEqual(data["prerequisite_subject_code"], "CS101")
        self.assertEqual(data["prerequisite_subject_name"], "Khoa học máy tính")


class Scrum124ProgramSubjectRepositoryUnitTests(unittest.TestCase):
    """Kiểm thử Unit logic và thuật toán Cycle Detection của ProgramSubjectRepository."""

    def test_01_cycle_detection_self_loop(self):
        # Môn A không được tự làm tiên quyết của A
        is_cycle = program_subject_repository.would_create_cycle("prog-1", "ps-A", "ps-A")
        self.assertTrue(is_cycle)

    @patch("app.repositories.program_subject_repository.get_prerequisite_graph_data")
    def test_02_cycle_detection_direct_loop(self, mock_graph):
        # Đã có: B là tiên quyết của A (cạnh B -> A)
        # Chuẩn bị thêm: A là tiên quyết của B (cạnh A -> B)
        # Sẽ tạo chu trình: B -> A -> B
        mock_graph.return_value = [("ps-B", "ps-A")]
        is_cycle = program_subject_repository.would_create_cycle("prog-1", "ps-A", "ps-B")
        self.assertTrue(is_cycle)

    @patch("app.repositories.program_subject_repository.get_prerequisite_graph_data")
    def test_03_cycle_detection_transitive_loop(self, mock_graph):
        # Đã có chuỗi tiên quyết: C -> B -> A (C là tiên quyết của B, B là tiên quyết của A)
        # Chuẩn bị thêm: A là tiên quyết của C (cạnh A -> C)
        # Sẽ tạo chu trình: C -> B -> A -> C
        mock_graph.return_value = [("ps-C", "ps-B"), ("ps-B", "ps-A")]
        is_cycle = program_subject_repository.would_create_cycle("prog-1", "ps-A", "ps-C")
        self.assertTrue(is_cycle)

    @patch("app.repositories.program_subject_repository.get_prerequisite_graph_data")
    def test_04_cycle_detection_valid_dag_edge(self, mock_graph):
        # Đã có: C -> B -> A
        # Chuẩn bị thêm: C là tiên quyết của A (cạnh C -> A) - DAG hợp lệ, không tạo chu trình
        mock_graph.return_value = [("ps-C", "ps-B"), ("ps-B", "ps-A")]
        is_cycle = program_subject_repository.would_create_cycle("prog-1", "ps-C", "ps-A")
        self.assertFalse(is_cycle)

    @patch("app.repositories.program_subject_repository.get_db_connection")
    def test_05_reorder_rollback_on_db_error(self, mock_get_conn):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        mock_cursor.execute.side_effect = MySQLError("Simulated MySQL update failure")

        with self.assertRaises(MySQLError):
            program_subject_repository.reorder_program_subjects("prog-1", 1, ["ps-1", "ps-2"])

        mock_conn.rollback.assert_called_once()


class Scrum124ProgramSubjectDatabaseIntegrationTests(unittest.TestCase):
    """
    Kiểm thử Tích hợp CSDL MySQL 8 thực tế:
    - Bảng program_subjects và program_subject_prerequisites
    - Các ràng buộc CHECK, UNIQUE, FOREIGN KEY
    - Ràng buộc Composite FK bảo đảm cùng program_id
    - Tự động kích hoạt live PROGRAM_IN_USE và SUBJECT_IN_USE (ON DELETE RESTRICT)
    """

    PREFIX = "SCRUM124-A1-"

    def setUp(self):
        self.created_prereq_ids = []
        self.created_ps_ids = []
        self.created_subject_ids = []
        self.created_program_ids = []

        # Chuẩn bị 2 chương trình đào tạo mẫu
        self.prog_1 = self._create_test_program("PROG1")
        self.prog_2 = self._create_test_program("PROG2")

        # Chuẩn bị 3 môn học mẫu
        self.subj_1 = self._create_test_subject("SUBJ1", "Cơ sở lập trình", 3)
        self.subj_2 = self._create_test_subject("SUBJ2", "Cấu trúc dữ liệu", 4)
        self.subj_3 = self._create_test_subject("SUBJ3", "Hệ quản trị CSDL", 3)

    def tearDown(self):
        # Dọn dẹp an toàn theo đúng thứ tự khóa ngoại
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # 1. Xóa prerequisites
                cursor.execute(
                    """
                    DELETE psp FROM program_subject_prerequisites psp
                    JOIN training_programs tp ON psp.program_id = tp.id
                    WHERE tp.code LIKE %s
                    """,
                    (f"{self.PREFIX}%",),
                )
                # 2. Xóa program_subjects
                cursor.execute(
                    """
                    DELETE ps FROM program_subjects ps
                    JOIN training_programs tp ON ps.program_id = tp.id
                    WHERE tp.code LIKE %s
                    """,
                    (f"{self.PREFIX}%",),
                )
                # 3. Xóa training_programs
                cursor.execute(
                    "DELETE FROM training_programs WHERE code LIKE %s",
                    (f"{self.PREFIX}%",),
                )
                # 4. Xóa subjects
                cursor.execute(
                    "DELETE FROM subjects WHERE code LIKE %s",
                    (f"{self.PREFIX}%",),
                )
            conn.commit()
        finally:
            conn.close()

    def _create_test_program(self, suffix: str) -> TrainingProgram:
        p_id = str(uuid.uuid4())
        code = f"{self.PREFIX}{suffix}-{uuid.uuid4().hex[:4].upper()}"
        prog = TrainingProgram(
            id=p_id,
            code=code,
            name=f"Chương trình đào tạo test {suffix}",
            duration_semesters=8,
            status=PROGRAM_STATUS_ACTIVE,
        )
        saved = training_program_repository.insert_training_program(prog)
        self.created_program_ids.append(saved.id)
        return saved

    def _create_test_subject(self, suffix: str, name: str, credits: int) -> Subject:
        s_id = str(uuid.uuid4())
        code = f"{self.PREFIX}{suffix}-{uuid.uuid4().hex[:4].upper()}"
        subj = Subject(
            id=s_id,
            code=code,
            name=f"{name} ({suffix})",
            credits=credits,
            status=SUBJECT_STATUS_ACTIVE,
        )
        saved = subject_repository.insert_subject(subj)
        self.created_subject_ids.append(saved.id)
        return saved

    def test_01_insert_and_get_program_subject_nullable_semester(self):
        # Thêm môn vào chương trình với semester = NULL
        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id=self.subj_1.id,
            semester=None,
            is_mandatory=True,
            order_index=1,
        )
        saved = program_subject_repository.insert_program_subject(ps)
        self.created_ps_ids.append(saved.id)

        fetched = program_subject_repository.get_program_subject_by_id(saved.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.program_id, self.prog_1.id)
        self.assertEqual(fetched.subject_id, self.subj_1.id)
        self.assertIsNone(fetched.semester)
        self.assertTrue(fetched.is_mandatory)
        self.assertEqual(fetched.subject_code, self.subj_1.code)
        self.assertEqual(fetched.subject_credits, 3)

    def test_02_mandatory_and_order_index_metadata_update(self):
        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id=self.subj_1.id,
            semester=1,
            is_mandatory=False,
            order_index=1,
        )
        saved = program_subject_repository.insert_program_subject(ps)
        self.created_ps_ids.append(saved.id)

        # Cập nhật metadata
        updated = program_subject_repository.update_program_subject_metadata(
            saved.id, semester=2, is_mandatory=True, order_index=5
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.semester, 2)
        self.assertTrue(updated.is_mandatory)
        self.assertEqual(updated.order_index, 5)

    def test_03_db_constraint_order_index_gte_1(self):
        # CHECK constraint: order_index >= 1
        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id=self.subj_1.id,
            semester=1,
            order_index=0,  # Sai constraint
        )
        with self.assertRaises((IntegrityError, DatabaseError)):
            program_subject_repository.insert_program_subject(ps)

    def test_04_db_constraint_duplicate_program_subject(self):
        # UNIQUE (program_id, subject_id)
        ps1 = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id=self.subj_1.id,
            semester=1,
            order_index=1,
        )
        program_subject_repository.insert_program_subject(ps1)
        self.created_ps_ids.append(ps1.id)

        ps2 = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id=self.subj_1.id,  # Cùng subject trong cùng program
            semester=2,
            order_index=2,
        )
        with self.assertRaises(IntegrityError):
            program_subject_repository.insert_program_subject(ps2)

    def test_05_db_constraint_invalid_program_fk(self):
        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id="non-existent-prog-uuid",
            subject_id=self.subj_1.id,
        )
        with self.assertRaises(IntegrityError):
            program_subject_repository.insert_program_subject(ps)

    def test_06_db_constraint_invalid_subject_fk(self):
        ps = ProgramSubject(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            subject_id="non-existent-subj-uuid",
        )
        with self.assertRaises(IntegrityError):
            program_subject_repository.insert_program_subject(ps)

    def test_07_prerequisite_same_program_success(self):
        # Gắn subj_1 và subj_2 vào prog_1
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1, order_index=1
        ))
        ps2 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_2.id, semester=2, order_index=1
        ))
        self.created_ps_ids.extend([ps1.id, ps2.id])

        # Gán ps1 làm môn tiên quyết của ps2 (ps1 -> ps2)
        prereq = ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps2.id,
            prerequisite_program_subject_id=ps1.id,
        )
        saved_prereq = program_subject_repository.insert_prerequisite(prereq)
        self.assertIsNotNone(saved_prereq)

        # Kiểm tra qua cấu trúc chương trình
        structure = program_subject_repository.get_program_structure(self.prog_1.id)
        self.assertEqual(len(structure), 2)
        ps2_in_struct = next(s for s in structure if s.id == ps2.id)
        self.assertEqual(len(ps2_in_struct.prerequisites), 1)
        self.assertEqual(ps2_in_struct.prerequisites[0]["prerequisite_subject_code"], self.subj_1.code)

    def test_08_cross_program_prerequisite_blocked_by_db_composite_fk(self):
        # ps1 ở prog_1
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        # ps_other ở prog_2
        ps_other = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_2.id, subject_id=self.subj_2.id, semester=1
        ))
        self.created_ps_ids.extend([ps1.id, ps_other.id])

        # Cố tình tạo prerequisite chéo chương trình:
        # ps_other (prog_2) làm tiên quyết cho ps1 (prog_1)
        cross_prereq = ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps1.id,
            prerequisite_program_subject_id=ps_other.id,  # Khác program_id!
        )
        # MySQL Composite FK fk_prereq_target: (program_id, prerequisite_program_subject_id) -> (program_id, id)
        # Sẽ từ chối ngay lập tức ở engine InnoDB!
        with self.assertRaises(IntegrityError):
            program_subject_repository.insert_prerequisite(cross_prereq)

    def test_09_self_prerequisite_blocked_by_db_check_constraint(self):
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        self.created_ps_ids.append(ps1.id)

        self_prereq = ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps1.id,
            prerequisite_program_subject_id=ps1.id,  # Self reference
        )
        with self.assertRaises((IntegrityError, DatabaseError)):
            program_subject_repository.insert_prerequisite(self_prereq)

    def test_10_duplicate_prerequisite_blocked(self):
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        ps2 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_2.id, semester=2
        ))
        self.created_ps_ids.extend([ps1.id, ps2.id])

        prereq1 = ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps2.id,
            prerequisite_program_subject_id=ps1.id,
        )
        program_subject_repository.insert_prerequisite(prereq1)

        prereq2 = ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps2.id,
            prerequisite_program_subject_id=ps1.id,
        )
        with self.assertRaises(IntegrityError):
            program_subject_repository.insert_prerequisite(prereq2)

    def test_11_source_delete_cascades_prerequisite_rows(self):
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        ps2 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_2.id, semester=2
        ))
        self.created_ps_ids.extend([ps1.id, ps2.id])

        prereq = program_subject_repository.insert_prerequisite(ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps2.id,
            prerequisite_program_subject_id=ps1.id,
        ))

        # Xóa ps2 (source của prerequisite)
        deleted = program_subject_repository.remove_program_subject(ps2.id)
        self.assertTrue(deleted)

        # Ràng buộc ON DELETE CASCADE của fk_prereq_source phải tự động dọn dòng prerequisite
        prereqs = program_subject_repository.get_prerequisites_by_program_subject_id(ps2.id)
        self.assertEqual(len(prereqs), 0)

    def test_12_target_delete_restricted_by_foreign_key(self):
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        ps2 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_2.id, semester=2
        ))
        self.created_ps_ids.extend([ps1.id, ps2.id])

        program_subject_repository.insert_prerequisite(ProgramSubjectPrerequisite(
            id=str(uuid.uuid4()),
            program_id=self.prog_1.id,
            program_subject_id=ps2.id,
            prerequisite_program_subject_id=ps1.id,
        ))

        # ps1 đang là prerequisite TARGET của ps2.
        # Ràng buộc fk_prereq_target là ON DELETE RESTRICT!
        with self.assertRaises(IntegrityError):
            program_subject_repository.remove_program_subject(ps1.id)

    def test_13_live_program_in_use_verification(self):
        # 1. Gắn môn học vào chương trình đào tạo
        ps = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        self.created_ps_ids.append(ps.id)

        # 2. Kiểm tra hàm nghiệp vụ của repository SCRUM-122
        is_in_use = training_program_repository.is_program_in_use(self.prog_1.id)
        self.assertTrue(is_in_use, "is_program_in_use phải trả về True khi đã có program_subjects")

        # 3. Kiểm tra khóa ngoại MySQL ON DELETE RESTRICT khi xóa training_program
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                with self.assertRaises(IntegrityError):
                    cursor.execute("DELETE FROM training_programs WHERE id = %s", (self.prog_1.id,))
        finally:
            conn.close()

    def test_14_live_subject_in_use_verification(self):
        # 1. Gắn môn học vào chương trình đào tạo
        ps = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1
        ))
        self.created_ps_ids.append(ps.id)

        # 2. Kiểm tra hàm nghiệp vụ của repository SCRUM-123
        is_in_use = subject_repository.is_subject_in_use(self.subj_1.id)
        self.assertTrue(is_in_use, "is_subject_in_use phải trả về True khi môn học nằm trong program_subjects")

        # 3. Kiểm tra khóa ngoại MySQL ON DELETE RESTRICT khi xóa subject
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                with self.assertRaises(IntegrityError):
                    cursor.execute("DELETE FROM subjects WHERE id = %s", (self.subj_1.id,))
        finally:
            conn.close()

    def test_15_reorder_and_normalize_order_indices(self):
        # Gắn 3 môn vào học kỳ 1
        ps1 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_1.id, semester=1, order_index=1
        ))
        ps2 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_2.id, semester=1, order_index=2
        ))
        ps3 = program_subject_repository.insert_program_subject(ProgramSubject(
            id=str(uuid.uuid4()), program_id=self.prog_1.id, subject_id=self.subj_3.id, semester=1, order_index=3
        ))
        self.created_ps_ids.extend([ps1.id, ps2.id, ps3.id])

        # Kéo thả hoán đổi: [ps3, ps1, ps2]
        program_subject_repository.reorder_program_subjects(self.prog_1.id, 1, [ps3.id, ps1.id, ps2.id])

        fetched3 = program_subject_repository.get_program_subject_by_id(ps3.id)
        fetched1 = program_subject_repository.get_program_subject_by_id(ps1.id)
        fetched2 = program_subject_repository.get_program_subject_by_id(ps2.id)

        self.assertEqual(fetched3.order_index, 1)
        self.assertEqual(fetched1.order_index, 2)
        self.assertEqual(fetched2.order_index, 3)

        # Gỡ ps1 (đang ở vị trí 2)
        program_subject_repository.remove_program_subject(ps1.id)
        # Chuẩn hóa lại thứ tự
        program_subject_repository.normalize_order_indices(self.prog_1.id, 1)

        rem3 = program_subject_repository.get_program_subject_by_id(ps3.id)
        rem2 = program_subject_repository.get_program_subject_by_id(ps2.id)

        self.assertEqual(rem3.order_index, 1)
        self.assertEqual(rem2.order_index, 2)


if __name__ == "__main__":
    unittest.main()
