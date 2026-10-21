-- Migration 036 (Seed Data): Dữ liệu mẫu Rubric & Bài tập chuẩn - SCRUM-268

-- 1. Thêm mẫu Rubric tiêu chuẩn
INSERT IGNORE INTO rubric_templates (id, name, description, created_by, is_deleted, created_at, updated_at)
VALUES (
    'tpl-seed-001',
    'Rubric Đánh Giá Đồ Án / Khóa Luận Tốt Nghiệp',
    'Mẫu rubric chuẩn gồm 3 tiêu chí chính: Mã nguồn, Báo cáo và Kỹ năng phản biện',
    'usr-admin-seed',
    0,
    NOW(),
    NOW()
);

-- 2. Thêm tiêu chí cho mẫu Rubric (Tổng trọng số: 40% + 35% + 25% = 100%)
INSERT IGNORE INTO rubric_criteria (id, template_id, name, description, max_score, weight, order_index, created_at, updated_at)
VALUES
    ('crit-seed-001', 'tpl-seed-001', 'Chất lượng Mã Nguồn & Kiến Trúc Phần Mềm', 'Mã nguồn sạch, có comment, áp dụng kiến trúc phân tầng', 10.00, 40.00, 1, NOW(), NOW()),
    ('crit-seed-002', 'tpl-seed-001', 'Độ Hoàn Thiện & Tính Năng Sản Phẩm', 'Chạy đúng chức năng theo yêu cầu đề bài, không phát sinh lỗi crash', 10.00, 35.00, 2, NOW(), NOW()),
    ('crit-seed-003', 'tpl-seed-001', 'Quy Cách Báo Cáo & Kỹ Năng Thuyết Trình', 'Trình bày rõ ràng, trả lời đúng trọng tâm câu hỏi của hội đồng', 10.00, 25.00, 3, NOW(), NOW());
