"""Initialize an empty, explicitly named MySQL test database from project SQL.

The database must already exist and its name must end in ``_test``. The script
refuses to run if any tables already exist. It never drops or clears data.
"""

import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "database" / "scripts"
MIGRATIONS = (
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
    "029_create_holidays_table.sql",
    "030_create_class_schedules_table.sql",
    "031_create_schedule_notifications_table.sql",
)


def _statements(sql_text: str) -> list[str]:
    without_full_line_comments = "\n".join(
        line for line in sql_text.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in without_full_line_comments.split(";") if statement.strip()]


def main() -> None:
    load_dotenv(ROOT / ".env", override=False)
    database = os.getenv("TEST_DB_NAME") or os.getenv("DB_NAME", "")
    if not database.endswith("_test"):
        raise SystemExit("Refusing to initialize a database whose name does not end in '_test'.")

    connection = mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=database,
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
            )
            existing_table_count = cursor.fetchone()[0]
            if existing_table_count:
                raise SystemExit(
                    f"Refusing non-empty test database {database!r} "
                    f"({existing_table_count} tables found)."
                )

            for migration in MIGRATIONS:
                sql_text = (SCRIPTS / migration).read_text(encoding="utf-8-sig")
                for statement in _statements(sql_text):
                    cursor.execute(statement)
                connection.commit()
                print(f"Applied {migration}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
