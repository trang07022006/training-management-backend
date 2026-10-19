# Class schedule API schema (SCRUM-217 to SCRUM-226)

The `/api/v1/classes/.../schedules` endpoints use `classes`, `class_schedules`,
and `schedule_notifications`. Their schema is defined by the numbered business
migrations below. `app/main.py` does not apply migrations at startup.

## Required migration order

Start from the project's core schema (`init.sql`) and RBAC migrations
(`001_create_roles_table.sql` through `005_seed_rbac_initial_data.sql`) when
setting up a new database. Then apply these migrations in order:

```text
009_create_training_programs_table.sql
010_create_subjects_table.sql
011_create_program_subjects_table.sql
012_create_leads_table.sql
013_create_subject_sessions_table.sql
014_add_lead_assignment.sql
015_add_tuition_fee_to_training_programs.sql
016_add_weight_and_learning_outcomes_to_subjects.sql
017_add_business_roles_and_permissions.sql
018_create_lead_assignment_history.sql
019_create_lead_status_history.sql
020_create_lead_care_logs.sql
021_create_students_table.sql
022_create_student_code_sequences_table.sql
023_add_must_change_password_to_users.sql
024_add_entry_level_and_notes_to_students.sql
025_create_classes_and_class_subjects.sql
026_create_class_enrollments_table.sql
029_create_holidays_table.sql
030_create_class_schedules_table.sql
031_create_schedule_notifications_table.sql
```

Migrations 012 and 018-020 require `training_programs` and `leads`; migration
021 requires `leads` and `training_programs`; migrations 025-026 require the
program, subject, student, and user tables; migrations 030-031 add the schedule
tables. The numbered files are manual SQL migrations, not startup code. Review
the target database and each migration's effects before applying them; several
use `ALTER TABLE` and are not safe to rerun blindly.

## Do not confuse the separate schedule schema

`008_create_training_schedule_tables.sql` creates a separate catalogue using
`training_classes` and `class_sessions`. It does **not** create `leads`,
`classes`, or `class_schedules`. Its `students` and `class_enrollments` tables
also have different columns and relationships from migrations 021 and 026.
Because those migrations use `CREATE TABLE IF NOT EXISTS`, they will silently
leave the alternate tables in place instead of upgrading them. Do not apply the
business migration sequence to a database containing the 008 schema until a
non-destructive reconciliation plan has been reviewed.

`ensure_business_roles()` only synchronizes role and permission records. Schema
creation is owned by the ordered SQL migrations; it is deliberately not run
implicitly when Flask imports the app.
