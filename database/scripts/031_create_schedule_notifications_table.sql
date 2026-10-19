-- SCRUM-226: Bảng lưu thông báo thay đổi thời khóa biểu (dời lịch, đổi phòng/giảng viên, hủy buổi học)
-- Gửi thông báo tới giảng viên và học viên của lớp theo AC 3
CREATE TABLE IF NOT EXISTS schedule_notifications (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    schedule_id VARCHAR(36) NOT NULL,
    class_id VARCHAR(36) NOT NULL,
    recipient_type VARCHAR(20) NOT NULL, -- 'instructor' | 'student'
    recipient_id VARCHAR(36) NOT NULL,
    recipient_name VARCHAR(255) NULL,
    recipient_email VARCHAR(255) NULL,
    change_type VARCHAR(50) NOT NULL, -- 'rescheduled' | 'cancelled' | 'updated'
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_sched_notif_class (class_id),
    INDEX idx_sched_notif_recipient (recipient_id),
    INDEX idx_sched_notif_schedule (schedule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
