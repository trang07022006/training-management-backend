"""Script áp dụng tất cả migrations an toàn vào cơ sở dữ liệu development (training_management).
Tự động bỏ qua các lỗi cột/bảng đã tồn tại (idempotent).
"""

import os
import sys
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "database" / "scripts"
load_dotenv(ROOT / ".env")

MIGRATIONS = [
    "init.sql",
    "001_create_roles_table.sql",
    "002_create_permissions_table.sql",
    "003_create_role_permissions_table.sql",
    "004_create_user_roles_table.sql",
    "005_seed_rbac_initial_data.sql",
    "002_create_password_reset_tokens.sql",
    "003_add_used_at_to_password_reset_tokens.sql",
    "006_add_name_phone_to_users.sql",
    "007_add_profile_fields_to_users.sql",
    "008_add_avatar_path_to_users.sql",
    "009_create_training_programs_table.sql",
    "010_create_subjects_table.sql",
    "011_create_program_subjects_table.sql",
    "012_create_leads_table.sql",
    "013_create_subject_sessions_table.sql",
    "014_add_lead_assignment.sql",
    "015_add_tuition_fee_to_training_programs.sql",
    "016_add_weight_and_learning_outcomes_to_subjects.sql",
    "017_add_business_roles_and_permissions.sql",
    "018_create_lead_assignment_history.sql",
    "019_create_lead_status_history.sql",
    "020_create_lead_care_logs.sql",
    "021_create_students_table.sql",
    "022_create_student_code_sequences_table.sql",
    "023_add_must_change_password_to_users.sql",
    "024_add_entry_level_and_notes_to_students.sql",
    "025_create_classes_and_class_subjects.sql",
    "026_create_class_enrollments_table.sql",
    "027_create_class_subject_instructors_table.sql",
    "028_create_classrooms_table.sql",
    "029_create_holidays_table.sql",
    "030_create_class_schedules_table.sql",
    "031_create_schedule_notifications_table.sql",
    "032_add_schedule_rbac_permissions.sql",
    "033_create_student_lifecycle_tables.sql",
    "034_create_attendance_tables.sql",
]


def _statements(sql_text: str) -> list[str]:
    without_full_line_comments = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in without_full_line_comments.split(";") if statement.strip()]


def main():
    db_name = os.getenv("DB_NAME", "training_management")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "3306"))
    db_user = os.getenv("DB_USER", "root")
    db_pass = os.getenv("DB_PASSWORD", "")

    print(f"Connecting to MySQL ({db_user}@{db_host}:{db_port}/{db_name})...")
    conn = mysql.connector.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_pass,
    )

    try:
        cursor = conn.cursor()
        for migration in MIGRATIONS:
            path = SCRIPTS / migration
            if not path.exists():
                print(f"[SKIP] {migration} (file not found)")
                continue

            sql_text = path.read_text(encoding="utf-8-sig")
            applied = True
            for stmt in _statements(sql_text):
                try:
                    cursor.execute(stmt)
                except mysql.connector.Error as err:
                    # Ignore duplicate column (1060), duplicate key/index (1061), table exists (1050), duplicate fk (1826/1022)
                    if err.errno in (1060, 1061, 1050, 1826, 1022):
                        pass
                    else:
                        print(f"  Warning on {migration}: {err.msg}")
                        applied = False
            conn.commit()
            if applied:
                print(f"[OK] Applied {migration}")

        print("\nSyncing RBAC data and demo accounts...")
        sys.path.insert(0, str(ROOT))
        from database.scripts.seed_demo_accounts import seed_demo_users
        from app.services.rbac_service import sync_initial_rbac_data, sync_business_rbac_data
        
        sync_initial_rbac_data()
        sync_business_rbac_data()
        seed_demo_users(conn)
        print("\nAll migrations & seed accounts applied successfully!")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
