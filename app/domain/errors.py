from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class FieldValidationError(Exception):
    title: str
    detail: str
    field_errors: Dict[str, str]

    def to_dict(self, request_id: str | None) -> Dict[str, Any]:
        return {
            "title": self.title,
            "detail": self.detail,
            "fieldErrors": self.field_errors,
            "requestId": request_id,
        }
