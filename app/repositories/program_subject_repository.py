from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
import uuid

from app.database.connection import get_db_connection
from app.models.program_subject import ProgramSubject
from app.models.program_subject_prerequisite import ProgramSubjectPrerequisite


def _to_mysql_datetime(value: datetime | None):
    """Chuyển đổi datetime sang UTC không timezone để lưu vào MySQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def _database_cursor(write: bool = False):
    """Quản lý kết nối, cursor và transaction cho một thao tác dữ liệu ProgramSubject."""
    connection = get_db_connection()
    try:
        with connection.cursor(dictionary=True) as cursor:
            yield cursor
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()


def _row_to_program_subject(row: dict) -> ProgramSubject:
    """Chuyển đổi dictionary row MySQL thành đối tượng ProgramSubject."""
    semester_val = row.get("semester")
    return ProgramSubject(
        id=str(row["id"]),
        program_id=str(row["program_id"]),
        subject_id=str(row["subject_id"]),
        semester=int(semester_val) if semester_val is not None else None,
        is_mandatory=bool(row.get("is_mandatory", True)),
        order_index=int(row.get("order_index", 1)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        subject_code=row.get("subject_code"),
        subject_name=row.get("subject_name"),
        subject_credits=int(row["subject_credits"]) if row.get("subject_credits") is not None else None,
        subject_total_sessions=int(row["subject_total_sessions"]) if row.get("subject_total_sessions") is not None else None,
        subject_status=row.get("subject_status"),
    )


def _row_to_prerequisite(row: dict) -> ProgramSubjectPrerequisite:
    """Chuyển đổi dictionary row MySQL thành đối tượng ProgramSubjectPrerequisite."""
    return ProgramSubjectPrerequisite(
        id=str(row["id"]),
        program_id=str(row["program_id"]),
        program_subject_id=str(row["program_subject_id"]),
        prerequisite_program_subject_id=str(row["prerequisite_program_subject_id"]),
        created_at=row.get("created_at"),
        prerequisite_subject_code=row.get("prerequisite_subject_code"),
        prerequisite_subject_name=row.get("prerequisite_subject_name"),
    )


def get_next_order_index(program_id: str, semester: int | None) -> int:
    """Lấy số thứ tự tiếp theo cho một học kỳ trong chương trình đào tạo."""
    if semester is None:
        sql = "SELECT COALESCE(MAX(order_index), 0) + 1 AS next_order FROM program_subjects WHERE program_id = %s AND semester IS NULL"
        params = (program_id,)
    else:
        sql = "SELECT COALESCE(MAX(order_index), 0) + 1 AS next_order FROM program_subjects WHERE program_id = %s AND semester = %s"
        params = (program_id, semester)
    with _database_cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return int(row["next_order"]) if row else 1


def insert_program_subject_ordered(
    program_subject: ProgramSubject,
    requested_order: int | None = None,
) -> ProgramSubject:
    """
    Thêm môn học vào chương trình đào tạo với thứ tự học được chỉ định (hoặc append cuối).
    Tự động dịch chuyển (shift) các môn học phía sau nếu chèn vào giữa,
    và chuẩn hóa lại dãy 1, 2, 3... trong cùng một transaction.
    """
    now = datetime.now(timezone.utc)
    ps_id = program_subject.id or str(uuid.uuid4())
    created_at = program_subject.created_at or now
    updated_at = program_subject.updated_at or now

    with _database_cursor(write=True) as cursor:
        if program_subject.semester is None:
            sem_filter = "semester IS NULL"
            sem_params = (program_subject.program_id,)
        else:
            sem_filter = "semester = %s"
            sem_params = (program_subject.program_id, program_subject.semester)

        if requested_order is not None and requested_order >= 1:
            shift_sql = f"""
                UPDATE program_subjects
                SET order_index = order_index + 1
                WHERE program_id = %s AND {sem_filter} AND order_index >= %s
            """
            cursor.execute(shift_sql, sem_params + (requested_order,))
            order_to_use = requested_order
        else:
            max_sql = f"SELECT COALESCE(MAX(order_index), 0) + 1 AS next_order FROM program_subjects WHERE program_id = %s AND {sem_filter}"
            cursor.execute(max_sql, sem_params)
            row = cursor.fetchone()
            order_to_use = int(row["next_order"]) if row else 1

        insert_sql = """
            INSERT INTO program_subjects (
                id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s
            )
        """
        insert_params = (
            ps_id,
            program_subject.program_id,
            program_subject.subject_id,
            program_subject.semester,
            1 if program_subject.is_mandatory else 0,
            order_to_use,
            _to_mysql_datetime(created_at),
            _to_mysql_datetime(updated_at),
        )
        cursor.execute(insert_sql, insert_params)

        sel_sql = f"SELECT id FROM program_subjects WHERE program_id = %s AND {sem_filter} ORDER BY order_index ASC, created_at ASC"
        cursor.execute(sel_sql, sem_params)
        all_rows = cursor.fetchall()

        upd_val = _to_mysql_datetime(now)
        for idx, r in enumerate(all_rows, start=1):
            upd_sql = "UPDATE program_subjects SET order_index = %s, updated_at = %s WHERE id = %s"
            cursor.execute(upd_sql, (idx, upd_val, r["id"]))

    res = get_program_subject_by_id(ps_id)
    return res if res else program_subject


def insert_program_subject(program_subject: ProgramSubject) -> ProgramSubject:
    """
    Thêm một môn học vào khung chương trình đào tạo (SCRUM-124 - Activity A1).
    Khởi tạo UUID nếu chưa có, gán thời gian UTC.
    """
    now = datetime.now(timezone.utc)
    ps_id = program_subject.id or str(uuid.uuid4())
    created_at = program_subject.created_at or now
    updated_at = program_subject.updated_at or now

    sql = """
        INSERT INTO program_subjects (
            id, program_id, subject_id, semester, is_mandatory, order_index, created_at, updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s
        )
    """
    params = (
        ps_id,
        program_subject.program_id,
        program_subject.subject_id,
        program_subject.semester,
        1 if program_subject.is_mandatory else 0,
        program_subject.order_index,
        _to_mysql_datetime(created_at),
        _to_mysql_datetime(updated_at),
    )

    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)

    fetched = get_program_subject_by_id(ps_id)
    if fetched:
        return fetched

    program_subject.id = ps_id
    program_subject.created_at = created_at
    program_subject.updated_at = updated_at
    return program_subject


def get_program_subject_by_id(program_subject_id: str) -> ProgramSubject | None:
    """
    Lấy thông tin chi tiết của một môn trong chương trình đào tạo theo ID,
    kèm thông tin môn học join từ bảng subjects.
    """
    sql = """
        SELECT
            ps.id, ps.program_id, ps.subject_id, ps.semester, ps.is_mandatory,
            ps.order_index, ps.created_at, ps.updated_at,
            s.code AS subject_code, s.name AS subject_name,
            s.credits AS subject_credits, s.total_sessions AS subject_total_sessions,
            s.status AS subject_status
        FROM program_subjects ps
        JOIN subjects s ON ps.subject_id = s.id
        WHERE ps.id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_subject_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_program_subject(row)


def get_program_subject_by_program_and_subject(program_id: str, subject_id: str) -> ProgramSubject | None:
    """Lấy thông tin quan hệ giữa program và subject nếu tồn tại."""
    sql = """
        SELECT
            ps.id, ps.program_id, ps.subject_id, ps.semester, ps.is_mandatory,
            ps.order_index, ps.created_at, ps.updated_at,
            s.code AS subject_code, s.name AS subject_name,
            s.credits AS subject_credits, s.total_sessions AS subject_total_sessions,
            s.status AS subject_status
        FROM program_subjects ps
        JOIN subjects s ON ps.subject_id = s.id
        WHERE ps.program_id = %s AND ps.subject_id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_id, subject_id))
        row = cursor.fetchone()
        if not row:
            return None
        return _row_to_program_subject(row)


def exists_program_subject(program_id: str, subject_id: str) -> bool:
    """Kiểm tra xem môn học đã được gắn vào chương trình đào tạo hay chưa."""
    sql = "SELECT 1 FROM program_subjects WHERE program_id = %s AND subject_id = %s LIMIT 1"
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_id, subject_id))
        return cursor.fetchone() is not None


def get_program_structure(program_id: str) -> list[ProgramSubject]:
    """
    Lấy toàn bộ cấu trúc môn học của một chương trình đào tạo,
    sắp xếp theo semester (NULL xếp sau) và order_index tăng dần.
    Đồng thời nạp danh sách điều kiện tiên quyết cho từng môn học.
    """
    sql = """
        SELECT
            ps.id, ps.program_id, ps.subject_id, ps.semester, ps.is_mandatory,
            ps.order_index, ps.created_at, ps.updated_at,
            s.code AS subject_code, s.name AS subject_name,
            s.credits AS subject_credits, s.total_sessions AS subject_total_sessions,
            s.status AS subject_status
        FROM program_subjects ps
        JOIN subjects s ON ps.subject_id = s.id
        WHERE ps.program_id = %s
        ORDER BY
            CASE WHEN ps.semester IS NULL THEN 1 ELSE 0 END,
            ps.semester ASC,
            ps.order_index ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_id,))
        rows = cursor.fetchall()

        items = [_row_to_program_subject(row) for row in rows]
        if not items:
            return []

        # Nạp tất cả prerequisites của program_id này trong 1 query duy nhất
        prereq_sql = """
            SELECT
                psp.id, psp.program_id, psp.program_subject_id,
                psp.prerequisite_program_subject_id, psp.created_at,
                s.code AS prerequisite_subject_code,
                s.name AS prerequisite_subject_name
            FROM program_subject_prerequisites psp
            JOIN program_subjects target_ps ON psp.prerequisite_program_subject_id = target_ps.id
            JOIN subjects s ON target_ps.subject_id = s.id
            WHERE psp.program_id = %s
        """
        cursor.execute(prereq_sql, (program_id,))
        prereq_rows = cursor.fetchall()

        prereq_map: dict[str, list[dict[str, Any]]] = {}
        for pr in prereq_rows:
            source_id = str(pr["program_subject_id"])
            if source_id not in prereq_map:
                prereq_map[source_id] = []
            prereq_map[source_id].append({
                "id": str(pr["id"]),
                "program_subject_id": source_id,
                "prerequisite_program_subject_id": str(pr["prerequisite_program_subject_id"]),
                "prerequisite_subject_code": pr.get("prerequisite_subject_code"),
                "prerequisite_subject_name": pr.get("prerequisite_subject_name"),
                "created_at": pr["created_at"].isoformat() if pr.get("created_at") else None,
            })

        for item in items:
            item.prerequisites = prereq_map.get(item.id, [])

        return items


def update_program_subject_metadata(
    program_subject_id: str,
    semester: int | None,
    is_mandatory: bool,
    order_index: int,
) -> ProgramSubject | None:
    """Cập nhật thông tin học kỳ, tính bắt buộc và thứ tự của một môn trong chương trình."""
    now = datetime.now(timezone.utc)
    sql = """
        UPDATE program_subjects
        SET
            semester = %s,
            is_mandatory = %s,
            order_index = %s,
            updated_at = %s
        WHERE id = %s
    """
    params = (
        semester,
        1 if is_mandatory else 0,
        order_index,
        _to_mysql_datetime(now),
        program_subject_id,
    )
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)

    return get_program_subject_by_id(program_subject_id)


def update_program_subject_fields(
    program_subject_id: str,
    fields: dict[str, Any],
) -> ProgramSubject | None:
    """
    Cập nhật từng phần thông tin môn học trong chương trình (PATCH).
    Chỉ cho phép cập nhật semester, is_mandatory, order_index.
    Tự động chuẩn hóa lại thứ tự (normalize order_index) nếu chuyển semester hoặc đổi thứ tự.
    """
    existing = get_program_subject_by_id(program_subject_id)
    if not existing:
        return None

    old_semester = existing.semester
    new_semester = fields.get("semester", old_semester)
    new_mandatory = fields.get("is_mandatory", existing.is_mandatory)
    new_order = fields.get("order_index", existing.order_index)

    now = datetime.now(timezone.utc)
    with _database_cursor(write=True) as cursor:
        sql = """
            UPDATE program_subjects
            SET semester = %s, is_mandatory = %s, order_index = %s, updated_at = %s
            WHERE id = %s
        """
        cursor.execute(sql, (
            new_semester,
            1 if new_mandatory else 0,
            new_order,
            _to_mysql_datetime(now),
            program_subject_id,
        ))

    normalize_order_indices(existing.program_id, new_semester)
    if old_semester != new_semester:
        normalize_order_indices(existing.program_id, old_semester)

    return get_program_subject_by_id(program_subject_id)


def remove_program_subject(program_subject_id: str) -> bool:
    """
    Gỡ một môn học khỏi khung chương trình đào tạo.
    Chỉ xóa dòng liên kết program_subjects, không xóa master training_program hay subject.
    Nếu môn này đang là prerequisite target của môn khác, FK RESTRICT sẽ bảo vệ dữ liệu.
    """
    sql = "DELETE FROM program_subjects WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (program_subject_id,))
        return cursor.rowcount > 0


def reorder_program_subjects(
    program_id: str,
    semester: int | None,
    ordered_ids: list[str],
) -> bool:
    """
    Chuẩn hóa và cập nhật lại thứ tự học (order_index: 1, 2, 3...) cho danh sách môn học
    trong cùng một chương trình và học kỳ. Chạy hoàn toàn trong một transaction duy nhất.
    """
    if not ordered_ids:
        return True

    now = datetime.now(timezone.utc)
    updated_at_val = _to_mysql_datetime(now)

    with _database_cursor(write=True) as cursor:
        for index, ps_id in enumerate(ordered_ids, start=1):
            if semester is None:
                sql = """
                    UPDATE program_subjects
                    SET order_index = %s, updated_at = %s
                    WHERE id = %s AND program_id = %s AND semester IS NULL
                """
                cursor.execute(sql, (index, updated_at_val, ps_id, program_id))
            else:
                sql = """
                    UPDATE program_subjects
                    SET order_index = %s, updated_at = %s
                    WHERE id = %s AND program_id = %s AND semester = %s
                """
                cursor.execute(sql, (index, updated_at_val, ps_id, program_id, semester))
    return True


def normalize_order_indices(program_id: str, semester: int | None) -> None:
    """
    Tự động chuẩn hóa order_index liên tục 1, 2, 3... cho các môn còn lại trong học kỳ
    sau thao tác gỡ môn (remove).
    """
    if semester is None:
        sql = """
            SELECT id FROM program_subjects
            WHERE program_id = %s AND semester IS NULL
            ORDER BY order_index ASC, created_at ASC
        """
        params = (program_id,)
    else:
        sql = """
            SELECT id FROM program_subjects
            WHERE program_id = %s AND semester = %s
            ORDER BY order_index ASC, created_at ASC
        """
        params = (program_id, semester)

    with _database_cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    ordered_ids = [str(r["id"]) for r in rows]
    if ordered_ids:
        reorder_program_subjects(program_id, semester, ordered_ids)


def insert_prerequisite(prerequisite: ProgramSubjectPrerequisite) -> ProgramSubjectPrerequisite:
    """
    Thêm một điều kiện môn tiên quyết (SCRUM-124 - Activity A1).
    Tự động sinh UUID và gán created_at nếu chưa có.
    """
    now = datetime.now(timezone.utc)
    p_id = prerequisite.id or str(uuid.uuid4())
    created_at = prerequisite.created_at or now

    sql = """
        INSERT INTO program_subject_prerequisites (
            id, program_id, program_subject_id, prerequisite_program_subject_id, created_at
        ) VALUES (
            %s, %s, %s, %s, %s
        )
    """
    params = (
        p_id,
        prerequisite.program_id,
        prerequisite.program_subject_id,
        prerequisite.prerequisite_program_subject_id,
        _to_mysql_datetime(created_at),
    )
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, params)

    prerequisite.id = p_id
    prerequisite.created_at = created_at
    return prerequisite


def remove_prerequisite(prerequisite_id: str) -> bool:
    """Xóa một ràng buộc điều kiện tiên quyết theo ID bản ghi."""
    sql = "DELETE FROM program_subject_prerequisites WHERE id = %s"
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (prerequisite_id,))
        return cursor.rowcount > 0


def remove_prerequisite_pair(
    program_id: str,
    program_subject_id: str,
    prerequisite_program_subject_id: str,
) -> bool:
    """Xóa một ràng buộc điều kiện tiên quyết theo cặp môn trong chương trình."""
    sql = """
        DELETE FROM program_subject_prerequisites
        WHERE program_id = %s
          AND program_subject_id = %s
          AND prerequisite_program_subject_id = %s
    """
    with _database_cursor(write=True) as cursor:
        cursor.execute(sql, (program_id, program_subject_id, prerequisite_program_subject_id))
        return cursor.rowcount > 0


def get_prerequisites_by_program_subject_id(
    program_subject_id: str,
) -> list[ProgramSubjectPrerequisite]:
    """Lấy danh sách tất cả các môn tiên quyết của môn học chỉ định."""
    sql = """
        SELECT
            psp.id, psp.program_id, psp.program_subject_id,
            psp.prerequisite_program_subject_id, psp.created_at,
            s.code AS prerequisite_subject_code,
            s.name AS prerequisite_subject_name
        FROM program_subject_prerequisites psp
        JOIN program_subjects target_ps ON psp.prerequisite_program_subject_id = target_ps.id
        JOIN subjects s ON target_ps.subject_id = s.id
        WHERE psp.program_subject_id = %s
        ORDER BY psp.created_at ASC
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_subject_id,))
        rows = cursor.fetchall()
        return [_row_to_prerequisite(r) for r in rows]


def get_dependent_program_subjects(
    prerequisite_program_subject_id: str,
) -> list[ProgramSubjectPrerequisite]:
    """Tìm tất cả các môn học đang phụ thuộc vào môn tiên quyết chỉ định (lookup ngược)."""
    sql = """
        SELECT
            psp.id, psp.program_id, psp.program_subject_id,
            psp.prerequisite_program_subject_id, psp.created_at
        FROM program_subject_prerequisites psp
        WHERE psp.prerequisite_program_subject_id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (prerequisite_program_subject_id,))
        rows = cursor.fetchall()
        return [_row_to_prerequisite(r) for r in rows]


def is_prerequisite_target(program_subject_id: str) -> bool:
    """Kiểm tra xem môn học có đang là môn tiên quyết cho bất kỳ môn nào khác hay không."""
    sql = "SELECT 1 FROM program_subject_prerequisites WHERE prerequisite_program_subject_id = %s LIMIT 1"
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_subject_id,))
        return cursor.fetchone() is not None


def get_prerequisite_graph_data(program_id: str) -> list[tuple[str, str]]:
    """
    Lấy danh sách tất cả các cạnh có hướng (u, v) trong đồ thị môn học của một chương trình.
    Quy ước cạnh: (prerequisite_id -> dependent_id) (môn B là tiên quyết của A => cạnh B -> A).
    """
    sql = """
        SELECT prerequisite_program_subject_id, program_subject_id
        FROM program_subject_prerequisites
        WHERE program_id = %s
    """
    with _database_cursor() as cursor:
        cursor.execute(sql, (program_id,))
        rows = cursor.fetchall()
        return [
            (str(r["prerequisite_program_subject_id"]), str(r["program_subject_id"]))
            for r in rows
        ]


def would_create_cycle(
    program_id: str,
    prerequisite_ps_id: str,
    dependent_ps_id: str,
) -> bool:
    """
    Kiểm tra thuật toán phát hiện chu trình (Cycle Detection):
    Quy ước cạnh: Prerequisite -> Dependent (B -> A).
    Trước khi thêm cạnh B -> A, kiểm tra xem đã tồn tại đường đi từ A -> ... -> B hay chưa.
    Nếu đã tồn tại đường đi từ A đến B, việc nối B -> A sẽ khép kín chu trình (A -> ... -> B -> A).
    Duyệt đồ thị bằng Breadth-First Search / Depth-First Search trong phạm vi cùng program_id.
    """
    if prerequisite_ps_id == dependent_ps_id:
        return True

    edges = get_prerequisite_graph_data(program_id)

    # Xây dựng danh sách kề (adjacency list): u -> [v1, v2, ...]
    adj: dict[str, list[str]] = {}
    for u, v in edges:
        if u not in adj:
            adj[u] = []
        adj[u].append(v)

    # Tìm kiếm đường đi từ dependent_ps_id (A) tới prerequisite_ps_id (B)
    queue = deque([dependent_ps_id])
    visited = {dependent_ps_id}

    while queue:
        curr = queue.popleft()
        if curr == prerequisite_ps_id:
            return True
        for neighbor in adj.get(curr, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return False
