from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ProgramSubjectPrerequisite:
    """
    Đại diện cho một ràng buộc môn tiên quyết trong cùng một chương trình đào tạo (SCRUM-124 - Activity A1).
    Môn prerequisite_program_subject_id là điều kiện tiên quyết của môn program_subject_id.
    """

    id: str
    program_id: str
    program_subject_id: str
    prerequisite_program_subject_id: str
    created_at: datetime | None = None

    # Thông tin join hỗ trợ (nếu có)
    prerequisite_subject_code: str | None = None
    prerequisite_subject_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi thực thể ProgramSubjectPrerequisite thành dictionary JSON-friendly."""
        data: dict[str, Any] = {
            "id": self.id,
            "program_id": self.program_id,
            "program_subject_id": self.program_subject_id,
            "prerequisite_program_subject_id": self.prerequisite_program_subject_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if self.prerequisite_subject_code is not None:
            data["prerequisite_subject_code"] = self.prerequisite_subject_code
        if self.prerequisite_subject_name is not None:
            data["prerequisite_subject_name"] = self.prerequisite_subject_name
        return data
