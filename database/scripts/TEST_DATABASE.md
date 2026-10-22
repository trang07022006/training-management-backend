# Isolated MySQL test database

Database-backed tests now target `training_management_test` by default. The
test configuration accepts `TEST_DB_NAME` only when the name ends in `_test`;
the `.env` development database name cannot override that choice.

## One-time setup

Create a dedicated empty database yourself, then point the bootstrap script at
it. The script refuses database names without the `_test` suffix and refuses
any database that already contains tables. It does not create the database,
drop tables, or clear data.

```powershell
mysql -u YOUR_MYSQL_USER -p -e "CREATE DATABASE training_management_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
$env:TEST_DB_NAME = "training_management_test"
python database/scripts/bootstrap_test_schema.py
```

The bootstrap applies the repository's existing SQL files in dependency order:
core users, RBAC, training programs, subjects, leads, lead history, students,
classes/enrollments, holidays, class schedules, and notifications. It excludes
`008_create_training_schedule_tables.sql`, which defines the separate
`training_classes`/`class_sessions` schema and incompatible `students` and
`class_enrollments` tables. It also includes the historical tuition migration,
which now checks for the column before adding it.

Run the database-backed tests only after this isolated schema setup:

```powershell
pytest tests/test_scrum129_subject_session_foundation.py -q -s -p no:cacheprovider
pytest tests/test_scrum224_schedule_generation_api.py tests/test_scrum225_schedule_conflicts_api.py tests/test_scrum226_reschedule_cancel_api.py -q -s -p no:cacheprovider
```

Do not point `TEST_DB_NAME` at a shared database. Test fixtures create and
delete their own UUID-keyed rows.
