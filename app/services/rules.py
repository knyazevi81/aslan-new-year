from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from app.services.expression import (
    Namespace,
    SafeEvalConfig,
    anySelected,
    coalesce,
    count,
    includes,
    safe_eval,
)
from app.services.schema_loader import Catalog


def compute_visibility(
    catalog: Catalog, answers: Dict[str, Any], computed: Dict[str, Any]
) -> Dict[str, bool]:
    """
    Apply rules type=visibility.
    Default: visible=True for all fields, then rules can set.
    """
    visible: Dict[str, bool] = {f["field_id"]: True for f in catalog.fields()}

    # Build env/cfg for rule expressions
    env = {
        "Decimal": Decimal,
        "answers": Namespace(answers),
        "computed": Namespace(computed),
        "params": Namespace({}),  # visibility rules in schema don't use params
        "pricing": Namespace({}),
        "includes": includes,
        "anySelected": anySelected,
        "count": count,
        "coalesce": coalesce,
        "min": min,
    }
    cfg = SafeEvalConfig(
        allowed_names=frozenset(env.keys()),
        allowed_callables=frozenset(
            {"Decimal", "includes", "anySelected", "count", "coalesce", "min"}
        ),
        allowed_attr_roots=frozenset({"answers", "computed", "params", "pricing"}),
    )

    for rule in catalog.rules():
        if rule.get("type") != "visibility":
            continue
        when_expr = rule.get("when", "true")
        cond = bool(safe_eval(when_expr, env, cfg))
        ops = rule.get("then", []) if cond else rule.get("else", [])
        for op in ops:
            if op.get("op") != "set_visible":
                continue
            fid = op["field_id"]
            if "value_expr" in op:
                val = bool(safe_eval(op["value_expr"], env, cfg))
            else:
                val = bool(op.get("value"))
            visible[fid] = val

    return visible


def clear_invisible_answers(answers: Dict[str, Any], visible: Dict[str, bool]) -> Dict[str, Any]:
    cleaned = dict(answers)
    for fid, is_vis in visible.items():
        if not is_vis and fid in cleaned:
            cleaned.pop(fid, None)
    return cleaned
