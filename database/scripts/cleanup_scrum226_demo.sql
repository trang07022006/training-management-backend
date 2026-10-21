-- Removes only SCRUM-226 demo IDs. Review IDs before running in any shared environment.
DELETE FROM schedule_notification_log
WHERE change_id IN (SELECT id FROM schedule_change_log WHERE session_id LIKE 'demo226-%');
DELETE FROM schedule_change_log WHERE session_id LIKE 'demo226-%';
DELETE FROM class_sessions WHERE id LIKE 'demo226-%';
DELETE FROM class_enrollments WHERE class_id LIKE 'demo226-%';
DELETE FROM training_classes WHERE id LIKE 'demo226-%';
DELETE FROM students WHERE id LIKE 'demo226-%';
DELETE FROM instructors WHERE id LIKE 'demo226-%';
DELETE FROM classrooms WHERE id LIKE 'demo226-%';
DELETE FROM courses WHERE id LIKE 'demo226-%';
