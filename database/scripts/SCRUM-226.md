# SCRUM-226 schedule backend and demo data

The migration creates a self-contained training catalogue and schedule domain. It does not modify `users`, authentication, RBAC, or existing email schema/data. The API uses existing `course.view` and `course.manage` permissions.

## Apply schema manually

Check the target database and its tables first. Run these commands only against a development/test database after confirming the selected database name:

```powershell
mysql -u <user> -p training_management < database/scripts/008_create_training_schedule_tables.sql
mysql -u <user> -p training_management < database/scripts/seed_scrum226_demo.sql
```

The application does not run these scripts automatically. Seed records use `demo226-` IDs, `[DEMO SCRUM-226]` names, and reserved `.invalid` email addresses. `INSERT IGNORE` does not update existing rows. Review database and IDs before running the cleanup script:

```powershell
mysql -u <user> -p training_management < database/scripts/cleanup_scrum226_demo.sql
```

Cleanup deletes only records whose IDs use `demo226-`, in foreign-key-safe order. It does not drop tables or delete users, RBAC records, or emails.

Demo scenarios:

- `demo226-edit-1`: edit topic, location, or time.
- `demo226-reschedule-1`: move to an available time.
- `demo226-collision-target`: moving to the blocker time on April 3, 2099 conflicts with `demo226-collision-blocker` for the same instructor and room.
- `demo226-cancel-1`: cancel one session and retain its record.
- Notification failure is exercised by mocked SMTP failure in the backend tests; seed never sends email.

## API

- `GET /api/schedule` and `GET /api/schedule/<id>` require `course.view`.
- `GET /api/schedule/<id>/notifications` reports delivery status.
- `PUT /api/schedule/<id>` edits the selected session.
- `POST /api/schedule/<id>/reschedule` moves the selected session.
- `POST /api/schedule/<id>/cancel` cancels the selected session.
- Mutation routes require `course.manage`. An optional `Idempotency-Key` (1–128 chars) prevents duplicate application of a retried operation.

Notification attempts happen after schedule and audit records commit. A delivery failure is stored as `failed` and does not roll back the schedule change. The `.invalid` demo addresses are not real recipients; never configure SMTP delivery for these records.

## Development checks

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_scrum226_schedule.py
```

Frontend pages are not included because this workspace contains only the Flask backend.
