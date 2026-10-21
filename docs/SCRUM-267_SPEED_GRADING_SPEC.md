# SCRUM-267: Màn Hình Chấm Điểm Bài Nộp Tốc Độ Cao (Speed Grading)

## 1. Mục Tiêu Nghiệp Vụ
Giúp Giảng viên có thể chấm điểm và viết nhận xét toàn bộ bài nộp của cả lớp (ví dụ 25 bài) trong một buổi tối mà **không phải mở nhiều cửa sổ hay quay lại danh sách lớp**.

## 2. Tiêu Chí Nghiệp Vụ (Acceptance Criteria)
1. **Xem trước tệp nộp & Mở liên kết Repo**:
   - Tệp nộp có link preview trực tiếp (PDF/Code/Image).
   - Có liên kết mở GitHub/GitLab Repository trực tiếp.
2. **Nhập điểm trong khoảng [0, max_score] kèm nhận xét**:
   - Backend validate điểm số chặt chẽ: $0 \le \text{score} \le \text{max\_score}$.
3. **Nút chuyển nhanh sang bài kế tiếp (Speed Grading Navigation)**:
   - API trả về `navigation: { prev_id, next_id, index, total }`.
   - Giảng viên lưu điểm và chuyển sang bài tiếp theo với 1 click hoặc phím tắt.
4. **Cơ chế Công Bố Điểm (Publishing)**:
   - Học viên không thấy điểm và nhận xét khi `is_published = 0`.
   - Giảng viên bấm **Công bố điểm** (`POST /api/v1/assignments/:id/publish-grades`) để đồng loạt hiển thị điểm cho học viên.
5. **Nhật Ký Sửa Điểm (Audit Log)**:
   - Bảng `submission_grade_audit_logs` lưu lại `old_score`, `new_score`, `old_feedback`, `new_feedback`, `change_reason`, `performed_by` và `created_at`.
