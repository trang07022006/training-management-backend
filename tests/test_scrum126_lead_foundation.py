"""
Kiểm thử nền tảng Quản lý Lead (SCRUM-126 - Activity A1).
Bao gồm:
1. Model Lead mở rộng (hỗ trợ status new, contacted, qualified, converted, lost, cancelled).
2. Kiểm tra validate_status, update_status.
3. Repository list_leads với phân trang và sắp xếp created_at DESC.
4. Repository update_lead_status cập nhật an toàn và trả về Lead mới nhất.
5. Kiểm thử tích hợp trực tiếp trên MySQL và dọn dẹp dữ liệu (cleanup).
"""

from datetime import datetime, timezone
import uuid
import pytest

from app.database.connection import get_db_connection
from app.models.lead import (
    LEAD_SOURCE_PUBLIC_FORM,
    LEAD_STATUS_CANCELLED,
    LEAD_STATUS_CONTACTED,
    LEAD_STATUS_CONVERTED,
    LEAD_STATUS_LOST,
    LEAD_STATUS_NEW,
    LEAD_STATUS_QUALIFIED,
    VALID_LEAD_STATUSES,
    Lead,
)
from app.repositories import lead_repository


class TestLeadModelFoundation:
    """Kiểm tra mô hình Lead và các phương thức cập nhật trạng thái."""

    def test_lead_model_supported_statuses(self):
        expected_statuses = {
            "new",
            "contacted",
            "qualified",
            "converted",
            "lost",
            "cancelled",
        }
        assert expected_statuses.issubset(VALID_LEAD_STATUSES)

    def test_lead_model_validate_status_success(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn Test",
            phone="0912345678",
            status=LEAD_STATUS_QUALIFIED,
        )
        lead.validate_status()
        assert lead.status == "qualified"

    def test_lead_model_validate_status_invalid_raises_error(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn Test",
            phone="0912345678",
            status="invalid_status",
        )
        with pytest.raises(ValueError, match="Trạng thái Lead không hợp lệ"):
            lead.validate_status()

    def test_lead_model_update_status_success(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn Test",
            phone="0912345678",
            status=LEAD_STATUS_NEW,
        )
        lead.update_status(LEAD_STATUS_CONTACTED)
        assert lead.status == "contacted"
        lead.update_status(LEAD_STATUS_QUALIFIED)
        assert lead.status == "qualified"
        lead.update_status(LEAD_STATUS_CONVERTED)
        assert lead.status == "converted"
        lead.update_status(LEAD_STATUS_LOST)
        assert lead.status == "lost"

    def test_lead_model_update_status_invalid_raises_error(self):
        lead = Lead(
            id=str(uuid.uuid4()),
            full_name="Nguyễn Văn Test",
            phone="0912345678",
            status=LEAD_STATUS_NEW,
        )
        with pytest.raises(ValueError, match="Trạng thái Lead không hợp lệ"):
            lead.update_status("unknown_status")


class TestLeadRepositoryFoundation:
    """Kiểm thử tầng truy xuất dữ liệu Repository với MySQL trực tiếp."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.created_lead_ids = []
        yield
        # Cleanup
        for lid in self.created_lead_ids:
            try:
                lead_repository.delete_lead_for_testing(lid)
            except Exception:
                pass

    def test_repository_insert_and_get_by_id(self):
        lead_id = str(uuid.uuid4())
        self.created_lead_ids.append(lead_id)

        lead = Lead(
            id=lead_id,
            full_name="Phạm Văn A",
            phone="0901112233",
            email="phamvana@example.com",
            message="Tìm hiểu ngành phần mềm",
            status=LEAD_STATUS_QUALIFIED,
        )
        inserted = lead_repository.insert_lead(lead)
        assert inserted.id == lead_id
        assert inserted.status == "qualified"

        fetched = lead_repository.get_lead_by_id(lead_id)
        assert fetched is not None
        assert fetched.id == lead_id
        assert fetched.full_name == "Phạm Văn A"
        assert fetched.status == "qualified"

    def test_repository_update_lead_status(self):
        lead_id = str(uuid.uuid4())
        self.created_lead_ids.append(lead_id)

        lead = Lead(
            id=lead_id,
            full_name="Hoàng Thị B",
            phone="0902223344",
            email="hoangb@example.com",
            status=LEAD_STATUS_NEW,
        )
        lead_repository.insert_lead(lead)

        # Cập nhật sang CONTACTED
        updated = lead_repository.update_lead_status(lead_id, LEAD_STATUS_CONTACTED)
        assert updated is not None
        assert updated.status == LEAD_STATUS_CONTACTED

        # Cập nhật sang LOST
        updated2 = lead_repository.update_lead_status(lead_id, LEAD_STATUS_LOST)
        assert updated2 is not None
        assert updated2.status == LEAD_STATUS_LOST

    def test_repository_update_lead_status_non_existent(self):
        non_existent_id = str(uuid.uuid4())
        result = lead_repository.update_lead_status(non_existent_id, LEAD_STATUS_CONTACTED)
        assert result is None

    def test_repository_list_leads_pagination(self):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        self.created_lead_ids.extend(ids)

        for i, lid in enumerate(ids):
            lead = Lead(
                id=lid,
                full_name=f"Lead Pagination Test {i}",
                phone=f"091100000{i}",
                status=LEAD_STATUS_NEW,
            )
            lead_repository.insert_lead(lead)

        leads, total = lead_repository.list_leads(page=1, page_size=10)
        assert total >= 3
        assert len(leads) >= 3

        # Đảm bảo các lead vừa tạo nằm trong danh sách
        retrieved_ids = {l.id for l in leads}
        for lid in ids:
            assert lid in retrieved_ids
