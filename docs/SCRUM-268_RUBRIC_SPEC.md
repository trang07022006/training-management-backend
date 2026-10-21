# SCRUM-268: Chấm điểm bài tập theo Rubric nhiều tiêu chí

## 1. Mục tiêu
Cho phép Giảng viên tạo mẫu Rubric gồm nhiều tiêu chí và trọng số (tổng trọng số 100%), gắn vào bài tập để chấm điểm công bằng, minh bạch. Học viên xem được điểm chi tiết từng tiêu chí và nhận xét từ giảng viên.

## 2. Công thức tính điểm
$$\text{Total Score} = \frac{\sum_{i=1}^{n} \left(\frac{\text{Score}_i}{\text{Max Score}_i} \times \text{Weight}_i\right)}{10}$$
- Quy về thang điểm 10.
- Điểm được làm tròn đến 2 chữ số thập phân.

## 3. Danh sách Endpoints
- `GET /api/v1/rubric-templates`: Xem danh sách mẫu rubric.
- `POST /api/v1/rubric-templates`: Tạo mẫu rubric mới (tổng weight = 100%).
- `GET /api/v1/rubric-templates/<id>`: Xem chi tiết mẫu rubric.
- `PATCH /api/v1/rubric-templates/<id>`: Cập nhật mẫu rubric / tiêu chí.
- `DELETE /api/v1/rubric-templates/<id>`: Xóa mềm mẫu rubric (nếu chưa gắn với bài tập).
- `GET /api/v1/classes/<class_id>/assignments`: Danh sách bài tập.
- `POST /api/v1/classes/<class_id>/assignments`: Tạo bài tập gắn rubric.
- `POST /api/v1/classes/<class_id>/assignments/<aid>/grades/<sid>`: Chấm điểm học viên.
- `GET /api/v1/classes/<class_id>/assignments/<aid>/my-grade`: Học viên xem điểm chi tiết.
