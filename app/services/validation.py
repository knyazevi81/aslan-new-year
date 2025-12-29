from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.domain.errors import FieldValidationError
from app.services.schema_loader import Catalog


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not int")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() != "":
        return int(value)
    raise ValueError("not int")


def _as_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    raise ValueError("not string")


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        # single selection might arrive as string
        return [value]
    raise ValueError("not string[]")


def validate_answers(
    catalog: Catalog,
    answers: Dict[str, Any],
    *,
    visible: Optional[Dict[str, bool]] = None,
    require_all_required: bool = True,
) -> Dict[str, Any]:
    """
    Strict schema validation:
    - unknown fields -> error
    - required fields -> error if missing (optionally)
    - data_type, constraints, dictionary membership
    - returns normalized answers (types cleaned)
    """
    field_defs = {f["field_id"]: f for f in catalog.fields()}
    field_errors: Dict[str, str] = {}
    normalized: Dict[str, Any] = {}

    # Unknown field ids
    for fid in answers.keys():
        if fid not in field_defs:
            field_errors[fid] = "Неизвестное поле (эльфы не знают, куда это положить)."

    # Validate known fields
    for fid, f in field_defs.items():
        if visible is not None and visible.get(fid) is False:
            # ignore/clear invisible fields
            continue

        provided = fid in answers and answers[fid] is not None and answers[fid] != ""
        if f.get("required") is True and require_all_required and not provided:
            field_errors[fid] = "Поле обязательно (без него магия не сработает)."
            continue

        if not provided:
            continue

        try:
            dt = f.get("data_type")
            val = answers[fid]
            if dt == "int":
                v = _as_int(val)
                constraints = f.get("constraints") or {}
                if "min" in constraints and v < int(constraints["min"]):
                    raise ValueError(f"Значение меньше минимума {constraints['min']}.")
                if "max" in constraints and v > int(constraints["max"]):
                    raise ValueError(f"Значение больше максимума {constraints['max']}.")
                if "step" in constraints:
                    step = int(constraints["step"])
                    minv = int(constraints.get("min", 0))
                    if step > 0 and ((v - minv) % step) != 0:
                        raise ValueError("Значение не попадает в шаг слайдера.")
                normalized[fid] = v

            elif dt == "decimal":
                # schema never asks user to enter decimal; it's computed. Still validate if provided.
                if isinstance(val, Decimal):
                    normalized[fid] = val
                elif isinstance(val, (int, float, str)):
                    normalized[fid] = Decimal(str(val))
                else:
                    raise ValueError("Ожидалось число.")

            elif dt == "string":
                v = _as_str(val)
                constraints = f.get("constraints") or {}
                if "min_length" in constraints and len(v) < int(constraints["min_length"]):
                    raise ValueError(f"Слишком коротко (мин. {constraints['min_length']}).")
                if "max_length" in constraints and len(v) > int(constraints["max_length"]):
                    raise ValueError(f"Слишком длинно (макс. {constraints['max_length']}).")
                normalized[fid] = v

            elif dt == "string[]":
                v = _as_str_list(val)
                # normalize unique while preserving order
                seen = set()
                uniq: List[str] = []
                for x in v:
                    if x not in seen:
                        seen.add(x)
                        uniq.append(x)
                normalized[fid] = uniq

            elif dt == "object":
                if not isinstance(val, dict):
                    raise ValueError("Ожидался объект.")
                normalized[fid] = val
            else:
                raise ValueError(f"Неподдерживаемый data_type: {dt}")

            # dictionary membership (for string or string[])
            dict_id = f.get("dictionary_id")
            if dict_id:
                allowed = {it["id"] for it in catalog.dictionary_items(dict_id)}
                if f.get("data_type") == "string":
                    if normalized[fid] not in allowed:
                        raise ValueError("Выбрано значение не из справочника.")
                if f.get("data_type") == "string[]":
                    bad = [x for x in normalized[fid] if x not in allowed]
                    if bad:
                        raise ValueError("Есть значения не из справочника: " + ", ".join(bad))

        except Exception as e:  # noqa: BLE001
            field_errors[fid] = str(e)

    if field_errors:
        raise FieldValidationError(
            title="Validation failed",
            detail="Эльфы нашли ошибки в анкете. Исправьте и попробуйте ещё раз.",
            field_errors=field_errors,
        )

    # Keep only validated + visible fields (if visible provided)
    if visible is not None:
        for fid, is_vis in visible.items():
            if not is_vis and fid in normalized:
                normalized.pop(fid, None)

    return normalized
