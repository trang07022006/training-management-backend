-- Synthetic SCRUM-226 demo records only. All IDs use demo226- and emails use .invalid.
-- INSERT IGNORE makes reruns non-destructive: existing rows are never updated.
INSERT IGNORE INTO courses (id, code, name, description) VALUES
('demo226-course-1', 'DEMO226-PY', '[DEMO SCRUM-226] Python căn bản', 'Synthetic data for schedule API development.');

INSERT IGNORE INTO instructors (id, name, email) VALUES
('demo226-instructor-1', '[DEMO SCRUM-226] Instructor One', 'instructor1@scrum226-demo.invalid');

INSERT IGNORE INTO students (id, name, email) VALUES
('demo226-student-1', '[DEMO SCRUM-226] Student One', 'student1@scrum226-demo.invalid'),
('demo226-student-2', '[DEMO SCRUM-226] Student Two', 'student2@scrum226-demo.invalid');

INSERT IGNORE INTO classrooms (id, name, location) VALUES
('demo226-room-1', '[DEMO SCRUM-226] Room One', 'Synthetic location'),
('demo226-room-2', '[DEMO SCRUM-226] Room Two', 'Synthetic location');

INSERT IGNORE INTO training_classes (id, course_id, instructor_id, classroom_id, name, delivery_mode) VALUES
('demo226-class-1', 'demo226-course-1', 'demo226-instructor-1', 'demo226-room-1', '[DEMO SCRUM-226] Class One', 'in_person');

INSERT IGNORE INTO class_enrollments (class_id, student_id) VALUES
('demo226-class-1', 'demo226-student-1'),
('demo226-class-1', 'demo226-student-2');

INSERT IGNORE INTO class_sessions (id, class_id, topic, starts_at, ends_at, classroom_id, status) VALUES
('demo226-edit-1', 'demo226-class-1', '[DEMO] Editable session', '2099-04-01 09:00:00', '2099-04-01 10:00:00', 'demo226-room-1', 'scheduled'),
('demo226-reschedule-1', 'demo226-class-1', '[DEMO] Reschedule target', '2099-04-02 09:00:00', '2099-04-02 10:00:00', 'demo226-room-1', 'scheduled'),
('demo226-collision-target', 'demo226-class-1', '[DEMO] Collision target', '2099-04-03 09:00:00', '2099-04-03 10:00:00', 'demo226-room-1', 'scheduled'),
('demo226-collision-blocker', 'demo226-class-1', '[DEMO] Collision blocker', '2099-04-03 11:00:00', '2099-04-03 12:00:00', 'demo226-room-1', 'scheduled'),
('demo226-cancel-1', 'demo226-class-1', '[DEMO] Cancellation target', '2099-04-04 09:00:00', '2099-04-04 10:00:00', 'demo226-room-1', 'scheduled');
