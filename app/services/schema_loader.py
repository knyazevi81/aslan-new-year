from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Catalog:
    raw: Dict[str, Any]

    def meta(self) -> Dict[str, Any]:
        return self.raw["meta"]

    def currency(self) -> str:
        return self.raw["meta"]["currency"]

    def engine(self) -> Dict[str, Any]:
        return self.raw["meta"]["engine"]

    def dictionaries(self) -> Dict[str, Any]:
        return self.raw["dictionaries"]

    def dictionary_items(self, dictionary_id: str) -> List[Dict[str, Any]]:
        return self.raw["dictionaries"][dictionary_id]["items"]

    def dictionary_item_by_id(self, dictionary_id: str, item_id: str) -> Optional[Dict[str, Any]]:
        for it in self.dictionary_items(dictionary_id):
            if it.get("id") == item_id:
                return it
        return None

    def screens(self) -> List[Dict[str, Any]]:
        return sorted(self.raw["inventory"]["screens"], key=lambda s: s.get("order", 0))

    def screen_by_id(self, screen_id: str) -> Dict[str, Any]:
        for s in self.raw["inventory"]["screens"]:
            if s["screen_id"] == screen_id:
                return s
        raise KeyError(f"Unknown screen_id: {screen_id}")

    def fields(self) -> List[Dict[str, Any]]:
        return self.raw["inventory"]["fields"]

    def field_by_id(self, field_id: str) -> Dict[str, Any]:
        for f in self.raw["inventory"]["fields"]:
            if f["field_id"] == field_id:
                return f
        raise KeyError(f"Unknown field_id: {field_id}")

    def fields_for_screen(self, screen_id: str, step: str | None = None) -> List[Dict[str, Any]]:
        result = [f for f in self.fields() if f["screen_id"] == screen_id]
        if step is not None:
            result = [f for f in result if f.get("step") == step]
        return result

    def rules(self) -> List[Dict[str, Any]]:
        return self.raw.get("rules", [])

    def computed(self) -> List[Dict[str, Any]]:
        return self.raw.get("computed", [])

    def pricing(self) -> Dict[str, Any]:
        return self.raw["pricing"]

    def actions(self) -> List[Dict[str, Any]]:
        return self.raw["inventory"].get("actions", [])

    def action_by_id(self, action_id: str) -> Dict[str, Any]:
        for a in self.actions():
            if a["action_id"] == action_id:
                return a
        raise KeyError(f"Unknown action_id: {action_id}")

    def required_field_ids(self) -> List[str]:
        return [f["field_id"] for f in self.fields() if f.get("required") is True]


@lru_cache(maxsize=1)
def load_catalog(schema_path: str = "catalog/schema.json") -> Catalog:
    path = Path(schema_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Catalog(raw=raw)
