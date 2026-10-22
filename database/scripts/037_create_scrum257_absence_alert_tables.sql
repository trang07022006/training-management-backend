-- SCRUM-257: Cảnh báo học viên vắng vượt ngưỡng
-- AC1: Ngưỡng cấu hình được theo chương trình, mặc định 20%
-- AC2: Học viên vượt ngưỡng được gắn cờ trên danh sách lớp và hồ sơ
-- AC3: Giảng viên và Quản lý đào tạo nhận thông báo khi cờ được bật

-- 1. Bổ sung cột absence_alert_threshold vào training_programs (mặc định 20%)
SET @has_absence_alert_threshold = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'training_programs'
      AND column_name = 'absence_alert_threshold'
);
SET @add_absence_alert_threshold_sql = IF(
    @has_absence_alert_threshold = 0,
    'ALTER TABLE training_programs ADD COLUMN absence_alert_threshold DECIMAL(5, 2) NOT NULL DEFAULT 20.00',
    'DO 0'
);
PREPARE add_absence_alert_threshold FROM @add_absence_alert_threshold_sql;
EXECUTE add_absence_alert_threshold;
DEALLOCATE PREPARE add_absence_alert_threshold;

-- 2. Bảng lưu vết lịch sử điều chỉnh ngưỡng của chương trình đào tạo (AC1 Audit)
CREATE TABLE IF NOT EXISTS program_absence_threshold_audits (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    program_id VARCHAR(36) NOT NULL,
    old_threshold DECIMAL(5, 2) NULL,
    new_threshold DECIMAL(5, 2) NOT NULL,
    changed_by VARCHAR(36) NOT NULL,
    changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reason VARCHAR(255) NULL,
    INDEX idx_prog_thresh_audit_prog (program_id),
    INDEX idx_prog_thresh_audit_changed_at (changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Bảng trạng thái cờ cảnh báo vắng vượt ngưỡng của học viên theo từng lớp (AC2)
CREATE TABLE IF NOT EXISTS student_absence_alerts (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    class_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    program_id VARCHAR(36) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active', -- 'active' (đang vượt ngưỡng) | 'inactive' (không vượt ngưỡng)
    absent_sessions INT NOT NULL DEFAULT 0,
    total_sessions INT NOT NULL DEFAULT 0,
    absence_rate DECIMAL(5, 2) NOT NULL DEFAULT 0.00,
    threshold DECIMAL(5, 2) NOT NULL DEFAULT 20.00,
    alert_round INT NOT NULL DEFAULT 1,
    first_triggered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_evaluated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME NULL,
    UNIQUE KEY uq_alert_class_student (class_id, student_id),
    INDEX idx_alert_class (class_id),
    INDEX idx_alert_student (student_id),
    INDEX idx_alert_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Bảng ghi nhận thông báo cảnh báo đã phát (AC3 - chống trùng lặp theo round & recipient)
CREATE TABLE IF NOT EXISTS absence_alert_notifications (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    alert_id VARCHAR(36) NOT NULL,
    alert_round INT NOT NULL DEFAULT 1,
    recipient_id VARCHAR(36) NOT NULL,
    recipient_role VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    class_id VARCHAR(36) NOT NULL,
    student_id VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE KEY uq_alert_round_recipient (alert_id, alert_round, recipient_id),
    INDEX idx_alert_notif_recipient (recipient_id),
    INDEX idx_alert_notif_class (class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
