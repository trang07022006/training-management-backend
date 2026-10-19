-- SCRUM-226: isolated training catalogue and schedule schema.
-- Does not alter users, authentication, RBAC, or existing email tables.
CREATE TABLE courses (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    description VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE instructors (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE students (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE classrooms (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    location VARCHAR(200) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE training_classes (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    course_id VARCHAR(64) NOT NULL,
    instructor_id VARCHAR(64) NOT NULL,
    classroom_id VARCHAR(64) NULL,
    name VARCHAR(160) NOT NULL,
    delivery_mode ENUM('in_person', 'online', 'hybrid') NOT NULL DEFAULT 'in_person',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_training_classes_course FOREIGN KEY (course_id) REFERENCES courses(id),
    CONSTRAINT fk_training_classes_instructor FOREIGN KEY (instructor_id) REFERENCES instructors(id),
    CONSTRAINT fk_training_classes_classroom FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
    INDEX idx_training_classes_instructor (instructor_id),
    INDEX idx_training_classes_classroom (classroom_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE class_enrollments (
    class_id VARCHAR(64) NOT NULL,
    student_id VARCHAR(64) NOT NULL,
    enrolled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (class_id, student_id),
    CONSTRAINT fk_class_enrollments_class FOREIGN KEY (class_id) REFERENCES training_classes(id) ON DELETE CASCADE,
    CONSTRAINT fk_class_enrollments_student FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
    INDEX idx_class_enrollments_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE class_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    class_id VARCHAR(64) NOT NULL,
    topic VARCHAR(200) NOT NULL,
    starts_at DATETIME NOT NULL,
    ends_at DATETIME NOT NULL,
    classroom_id VARCHAR(64) NULL,
    status ENUM('scheduled', 'completed', 'cancelled') NOT NULL DEFAULT 'scheduled',
    cancellation_reason VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_class_sessions_class FOREIGN KEY (class_id) REFERENCES training_classes(id),
    CONSTRAINT fk_class_sessions_classroom FOREIGN KEY (classroom_id) REFERENCES classrooms(id),
    CONSTRAINT chk_class_sessions_duration CHECK (ends_at > starts_at),
    INDEX idx_class_sessions_class_time (class_id, starts_at),
    INDEX idx_class_sessions_status_time (status, starts_at),
    INDEX idx_class_sessions_classroom_time (classroom_id, starts_at, ends_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE schedule_change_log (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    actor_user_id VARCHAR(64) NOT NULL,
    action ENUM('edited', 'rescheduled', 'cancelled') NOT NULL,
    old_values JSON NOT NULL,
    new_values JSON NOT NULL,
    request_key VARCHAR(128) NULL UNIQUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_schedule_change_session FOREIGN KEY (session_id) REFERENCES class_sessions(id),
    INDEX idx_schedule_change_session_time (session_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE schedule_notification_log (
    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    change_id BIGINT NOT NULL,
    recipient_email VARCHAR(255) NOT NULL,
    status ENUM('pending', 'sent', 'failed') NOT NULL DEFAULT 'pending',
    error_code VARCHAR(64) NULL,
    attempted_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_schedule_notification_change FOREIGN KEY (change_id) REFERENCES schedule_change_log(id) ON DELETE CASCADE,
    UNIQUE KEY uq_schedule_notification_recipient (change_id, recipient_email),
    INDEX idx_schedule_notification_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
