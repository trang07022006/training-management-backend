-- Migration 011: Tạo bảng cấu trúc chương trình đào tạo (SCRUM-124)
-- Quản lý môn học trong chương trình đào tạo và điều kiện tiên quyết (Prerequisites)

CREATE TABLE IF NOT EXISTS program_subjects (
    id VARCHAR(36) NOT NULL,
    program_id VARCHAR(36) NOT NULL,
    subject_id VARCHAR(36) NOT NULL,
    semester SMALLINT UNSIGNED NULL,
    is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
    order_index SMALLINT UNSIGNED NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_program_subjects (program_id, subject_id),
    UNIQUE KEY uq_program_subjects_prog_id (program_id, id),
    KEY idx_program_subjects_subject (subject_id),
    KEY idx_program_subjects_order (program_id, semester, order_index),
    CONSTRAINT fk_program_subjects_program FOREIGN KEY (program_id)
        REFERENCES training_programs(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_program_subjects_subject FOREIGN KEY (subject_id)
        REFERENCES subjects(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_program_subjects_semester CHECK (semester IS NULL OR semester >= 1),
    CONSTRAINT chk_program_subjects_order CHECK (order_index >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS program_subject_prerequisites (
    id VARCHAR(36) NOT NULL,
    program_id VARCHAR(36) NOT NULL,
    program_subject_id VARCHAR(36) NOT NULL,
    prerequisite_program_subject_id VARCHAR(36) NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_prog_subj_prereq (program_subject_id, prerequisite_program_subject_id),
    KEY idx_prereq_target (prerequisite_program_subject_id),
    KEY idx_prereq_prog_target (program_id, prerequisite_program_subject_id),
    CONSTRAINT fk_prereq_source FOREIGN KEY (program_id, program_subject_id)
        REFERENCES program_subjects(program_id, id) ON DELETE CASCADE ON UPDATE RESTRICT,
    CONSTRAINT fk_prereq_target FOREIGN KEY (program_id, prerequisite_program_subject_id)
        REFERENCES program_subjects(program_id, id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT chk_prereq_no_self CHECK (program_subject_id <> prerequisite_program_subject_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
