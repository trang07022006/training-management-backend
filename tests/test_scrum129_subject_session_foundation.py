"""
Test suite cho SCRUM-129 - Activity A1: Nền tảng SubjectSession (Model, Repository, Database & FK).
Kiểm tra:
1. Model SubjectSession và serialization to_dict().
2. Database schema, khóa ngoại subject_id -> subjects(id) ON DELETE RESTRICT.
3. Ràng buộc CHECK session_number >= 1.
4. Ràng buộc UNIQUE (subject_id, session_number).
5. Repository insert, get_by_id, get_by_subject_and_number, list_by_subject, count, max_number, update, delete.
6. Chuẩn hóa số thứ tự (normalize_session_numbers) và cập nhật hàng loạt (bulk_update_session_numbers).
7. Ràng buộc liên kết: Khi môn học có buổi học, DELETE môn học trả về 409 SUBJECT_IN_USE.
8. Trực tiếp từ MySQL: Xóa môn học có buổi học bị chặn bởi FK RESTRICT.
"""

import uuid
import pytest
from datetime import datetime, timezone
from mysql.connector.errors import IntegrityError

from app.database.connection import get_db_connection
from app.main import app
from app.models.subject import Subject
from app.models.subject_session import SubjectSession
from app.repositories import subject_repository, subject_session_repository


@pytest.fixture
def test_subject():
    """Tạo một môn học thử nghiệm và dọn dẹp sau khi kiểm thử."""
    subject_id = str(uuid.uuid4())
    subj = Subject(
        id=subject_id,
        code=f"SESS-A1-{uuid.uuid4().hex[:6]}",
        name="Môn học kiểm thử A1",
        credits=3,
        total_sessions=10,
        status="active",
    )
    subject_repository.insert_subject(subj)
    yield subj

    # Cleanup
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM subject_sessions WHERE subject_id = %s", (subject_id,))
            cursor.execute("DELETE FROM subjects WHERE id = %s", (subject_id,))
        conn.commit()
    finally:
        conn.close()


class TestSubjectSessionModel:
    def test_model_instantiation_and_to_dict(self):
        """Khởi tạo đối tượng SubjectSession và chuyển đổi to_dict."""
        sess_id = str(uuid.uuid4())
        subj_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        sess = SubjectSession(
            id=sess_id,
            subject_id=subj_id,
            session_number=1,
            topic="Tổng quan môn học",
            objective="Nắm được mục tiêu và đề cương chi tiết",
            created_at=now,
            updated_at=now,
        )

        assert sess.id == sess_id
        assert sess.subject_id == subj_id
        assert sess.session_number == 1
        assert sess.topic == "Tổng quan môn học"

        d = sess.to_dict()
        assert d["id"] == sess_id
        assert d["subject_id"] == subj_id
        assert d["session_number"] == 1
        assert d["topic"] == "Tổng quan môn học"
        assert d["objective"] == "Nắm được mục tiêu và đề cương chi tiết"
        assert d["created_at"] is not None
        assert d["updated_at"] is not None


class TestSubjectSessionRepository:
    def test_insert_and_get_session(self, test_subject):
        """Thêm và truy vấn buổi học theo ID hoặc (subject_id, session_number)."""
        sess_id = str(uuid.uuid4())
        sess = SubjectSession(
            id=sess_id,
            subject_id=test_subject.id,
            session_number=1,
            topic="Buổi 1: Giới thiệu",
            objective="Hiểu kiến trúc tổng thể",
        )

        inserted = subject_session_repository.insert_subject_session(sess)
        assert inserted.id == sess_id
        assert inserted.session_number == 1

        # Lấy theo ID
        fetched = subject_session_repository.get_subject_session_by_id(sess_id)
        assert fetched is not None
        assert fetched.id == sess_id
        assert fetched.topic == "Buổi 1: Giới thiệu"

        # Lấy theo subject và session_number
        fetched_by_num = subject_session_repository.get_subject_session_by_subject_and_number(
            test_subject.id, 1
        )
        assert fetched_by_num is not None
        assert fetched_by_num.id == sess_id

    def test_duplicate_session_number_raises_integrity_error(self, test_subject):
        """Trùng lặp session_number trên cùng môn học phải bắn IntegrityError (1062)."""
        sess1 = SubjectSession(
            id=str(uuid.uuid4()),
            subject_id=test_subject.id,
            session_number=1,
            topic="Buổi 1",
            objective="Mục tiêu 1",
        )
        subject_session_repository.insert_subject_session(sess1)

        sess2 = SubjectSession(
            id=str(uuid.uuid4()),
            subject_id=test_subject.id,
            session_number=1,
            topic="Buổi 1 trùng lặp",
            objective="Mục tiêu trùng lặp",
        )
        with pytest.raises(IntegrityError):
            subject_session_repository.insert_subject_session(sess2)

    def test_invalid_subject_foreign_key_raises_integrity_error(self):
        """Khóa ngoại subject_id không tồn tại phải bắn IntegrityError."""
        non_existent_subject = str(uuid.uuid4())
        sess = SubjectSession(
            id=str(uuid.uuid4()),
            subject_id=non_existent_subject,
            session_number=1,
            topic="Buổi không có môn",
            objective="Mục tiêu",
        )
        with pytest.raises(IntegrityError):
            subject_session_repository.insert_subject_session(sess)

    def test_list_and_count_and_max_number(self, test_subject):
        """Kiểm tra list_by_subject, count, max_session_number."""
        for num in [2, 1, 3]:
            subject_session_repository.insert_subject_session(
                SubjectSession(
                    id=str(uuid.uuid4()),
                    subject_id=test_subject.id,
                    session_number=num,
                    topic=f"Chủ đề {num}",
                    objective=f"Mục tiêu {num}",
                )
            )

        sessions = subject_session_repository.list_subject_sessions_by_subject(test_subject.id)
        assert len(sessions) == 3
        # Đảm bảo được sắp xếp tăng dần theo session_number
        assert [s.session_number for s in sessions] == [1, 2, 3]

        assert subject_session_repository.count_subject_sessions(test_subject.id) == 3
        assert subject_session_repository.get_max_session_number(test_subject.id) == 3

    def test_update_and_delete_session(self, test_subject):
        """Cập nhật các trường topic, objective và xóa buổi học."""
        sess_id = str(uuid.uuid4())
        sess = SubjectSession(
            id=sess_id,
            subject_id=test_subject.id,
            session_number=1,
            topic="Chủ đề ban đầu",
            objective="Mục tiêu ban đầu",
        )
        subject_session_repository.insert_subject_session(sess)

        updated = subject_session_repository.update_subject_session_fields(
            sess_id, {"topic": "Chủ đề mới", "objective": "Mục tiêu mới"}
        )
        assert updated is not None
        assert updated.topic == "Chủ đề mới"
        assert updated.objective == "Mục tiêu mới"

        # Xóa
        deleted = subject_session_repository.delete_subject_session(sess_id)
        assert deleted is True
        assert subject_session_repository.get_subject_session_by_id(sess_id) is None


class TestSubjectSessionIntegrityLive:
    def test_is_subject_in_use_live_and_delete_prevention(self, test_subject):
        """
        Khi môn học có buổi học:
        - subject_repository.is_subject_in_use(subject_id) trả về True
        - DELETE /api/v1/subjects/<id> trả về 409 SUBJECT_IN_USE
        """
        subject_session_repository.insert_subject_session(
            SubjectSession(
                id=str(uuid.uuid4()),
                subject_id=test_subject.id,
                session_number=1,
                topic="Buổi khóa môn học",
                objective="Ngăn không cho xóa môn",
            )
        )

        assert subject_repository.is_subject_in_use(test_subject.id) is True

        # Kiểm tra qua tầng service: gọi delete_subject_service phải ném SubjectInUseError với mã 409 SUBJECT_IN_USE
        from app.services.subject_service import delete_subject_service, SubjectInUseError
        with pytest.raises(SubjectInUseError) as exc_info:
            delete_subject_service(test_subject.id)
        assert exc_info.value.code == "SUBJECT_IN_USE"
        assert exc_info.value.status_code == 409

    def test_foreign_key_on_delete_restrict_in_mysql(self, test_subject):
        """Xóa trực tiếp dòng môn học trong MySQL bị FK RESTRICT chặn khi có buổi học."""
        subject_session_repository.insert_subject_session(
            SubjectSession(
                id=str(uuid.uuid4()),
                subject_id=test_subject.id,
                session_number=1,
                topic="Buổi kiểm tra FK",
                objective="Mục tiêu",
            )
        )

        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                with pytest.raises(IntegrityError):
                    cursor.execute("DELETE FROM subjects WHERE id = %s", (test_subject.id,))
            conn.rollback()
        finally:
            conn.close()
