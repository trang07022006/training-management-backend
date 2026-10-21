# Cấu Trúc Database SCRUM-268: Rubric & Assignment Grading

## 1. Sơ đồ Thực thể Quan hệ (ERD)
- `rubric_templates` (1) ───< `rubric_criteria` (N) [CASCADE DELETE]
- `rubric_templates` (1) ───< `assignments` (N) [SET NULL]
- `assignments` (1) ───< `assignment_grades` (N) [CASCADE DELETE]
- `assignment_grades` (1) ───< `assignment_criteria_grades` (N) [CASCADE DELETE]
- `rubric_criteria` (1) ───< `assignment_criteria_grades` (N) [RESTRICT]

## 2. Bảng `rubric_templates`
| Cột | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `id` | VARCHAR(36) PK | UUID định danh mẫu rubric |
| `name` | VARCHAR(255) | Tên mẫu rubric |
| `description` | TEXT | Mô tả mục đích sử dụng |
| `created_by` | VARCHAR(36) FK | ID người tạo (users.id) |
| `is_deleted` | TINYINT(1) | Trạng thái xóa mềm (0: active, 1: deleted) |

## 3. Bảng `rubric_criteria`
| Cột | Kiểu | Mô tả |
| :--- | :--- | :--- |
| `id` | VARCHAR(36) PK | UUID định danh tiêu chí |
| `template_id` | VARCHAR(36) FK | Liên kết tới rubric_templates.id |
| `name` | VARCHAR(255) | Tên tiêu chí |
| `weight` | DECIMAL(5,2) | Trọng số phần trăm (tổng trong 1 template = 100) |
| `max_score` | DECIMAL(5,2) | Điểm tối đa của tiêu chí (mặc định 10.00) |
| `order_index` | INT | Thứ tự hiển thị |

## 4. Bảng `assignment_grades` & `assignment_criteria_grades`
- `assignment_grades`: Lưu điểm tổng kết (`total_score` tính tự động quy về thang 10) và feedback chung.
- `assignment_criteria_grades`: Lưu chi tiết điểm từng tiêu chí (`score`) và giải thích mất điểm (`comment`).
