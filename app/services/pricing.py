from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from app.domain.pricing import PricingMultiplier, PricingState
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


def build_params(catalog: Catalog) -> Dict[str, Decimal]:
    params: Dict[str, Decimal] = {}
    for p in catalog.pricing()["parameters"]:
        key = p["key"]
        default = p.get("default")
        # defaults in schema are numbers; keep exact string if possible
        params[key] = Decimal(str(default)) if default is not None else Decimal("0")
    return params


def compute_computed(
    catalog: Catalog, answers: Dict[str, Any], params: Dict[str, Decimal]
) -> Dict[str, Any]:
    env = {
        "Decimal": Decimal,
        "answers": Namespace(answers),
        "computed": Namespace({}),
        "params": Namespace(params),
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
    computed: Dict[str, Any] = {}
    # compute sequentially; computed can reference computed in this schema? not used, but support anyway.
    for c in catalog.computed():
        cid = c["computed_id"]
        env["computed"] = Namespace(computed)
        computed[cid] = safe_eval(c["expr"], env, cfg)
    return computed


def sumRiskWeights(catalog: Catalog, *risk_arrays: List[str]) -> int:
    risks = {it["id"]: int(it.get("weight", 0)) for it in catalog.dictionary_items("DICT_RISKS")}
    total = 0
    for arr in risk_arrays:
        for rid in arr or []:
            total += risks.get(rid, 0)
    return total


def _computeTariffTotal(
    catalog: Catalog, answers: Dict[str, Any], pricing: PricingState, params: Dict[str, Decimal]
) -> Decimal:
    expr = catalog.pricing()["tariff_formula"]["tariff_total_expr"]
    env = _pricing_env(catalog, answers, pricing, params)
    cfg = _pricing_cfg(env)
    value = safe_eval(expr, env, cfg)
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value


def _computePremiumTotal(
    catalog: Catalog, answers: Dict[str, Any], pricing: PricingState, params: Dict[str, Decimal]
) -> int:
    expr = catalog.pricing()["tariff_formula"]["premium_total_expr"]
    env = _pricing_env(catalog, answers, pricing, params)
    cfg = _pricing_cfg(env)
    value = safe_eval(expr, env, cfg)
    # round(...) may return Decimal or int; normalize to int
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def _computeBreakdown(
    catalog: Catalog, answers: Dict[str, Any], pricing: PricingState, params: Dict[str, Decimal]
) -> Dict[str, Any]:
    # Per extensions spec: object with required keys
    return pricing.breakdown()


def _pricing_env(
    catalog: Catalog, answers: Dict[str, Any], pricing: PricingState, params: Dict[str, Decimal]
) -> Dict[str, Any]:
    # Provide helper functions required by schema.extensions.pricing_helpers_spec
    def computeTariffTotal() -> Decimal:
        return _computeTariffTotal(catalog, answers, pricing, params)

    def computePremiumTotal() -> int:
        # ensure pricing.tariff_total is current
        return _computePremiumTotal(catalog, answers, pricing, params)

    def computeBreakdown() -> Dict[str, Any]:
        return _computeBreakdown(catalog, answers, pricing, params)

    def _sumRiskWeights(*arrays: List[str]) -> int:
        return sumRiskWeights(catalog, *arrays)

    env = {
        "Decimal": Decimal,
        "answers": Namespace(answers),
        "computed": Namespace({}),  # will be replaced
        "params": Namespace(params),
        "pricing": pricing,  # PricingState uses attributes (dataclass)
        "includes": includes,
        "anySelected": anySelected,
        "count": count,
        "coalesce": coalesce,
        "min": min,
        "round": round,
        "sumRiskWeights": _sumRiskWeights,
        "computeTariffTotal": computeTariffTotal,
        "computePremiumTotal": computePremiumTotal,
        "computeBreakdown": computeBreakdown,
    }
    return env


def _pricing_cfg(env: Dict[str, Any]) -> SafeEvalConfig:
    return SafeEvalConfig(
        allowed_names=frozenset(env.keys()),
        allowed_callables=frozenset(
            {
                "Decimal",
                "includes",
                "anySelected",
                "count",
                "coalesce",
                "min",
                "round",
                "sumRiskWeights",
                "computeTariffTotal",
                "computePremiumTotal",
                "computeBreakdown",
            }
        ),
        allowed_attr_roots=frozenset({"answers", "computed", "params", "pricing"}),
    )


def execute_pricing(
    catalog: Catalog, answers: Dict[str, Any], computed: Dict[str, Any], params: Dict[str, Decimal]
) -> Tuple[PricingState, Dict[str, Any]]:
    pricing = PricingState()
    env = _pricing_env(catalog, answers, pricing, params)
    env["computed"] = Namespace(computed)
    cfg = _pricing_cfg(env)

    # execute pricing rules in order
    for rule in catalog.rules():
        if rule.get("type") != "pricing":
            continue
        when_expr = rule.get("when", "true")
        if not bool(safe_eval(when_expr, env, cfg)):
            continue
        for op in rule.get("then", []):
            opname = op.get("op")
            if opname == "pricing_reset":
                pricing = PricingState()
                env["pricing"] = pricing

            elif opname == "pricing_set":
                key = op["key"]
                val = safe_eval(op["value_expr"], env, cfg)
                if key in {"base_rate", "factor_per_risk_unit", "deductible_discount"}:
                    val = Decimal(str(val))
                if key == "risk_weight_sum":
                    val = int(val)
                setattr(pricing, key, val)

            elif opname == "pricing_add_multiplier":
                code = op["code"]
                mval = safe_eval(op["multiplier_expr"], env, cfg)
                mval_d = Decimal(str(mval))
                note = None
                if op.get("note_expr") is not None:
                    note_v = safe_eval(op["note_expr"], env, cfg)
                    note = None if note_v is None else str(note_v)
                pricing.multipliers.append(PricingMultiplier(code=code, value=mval_d, note=note))

            elif opname == "pricing_compute":
                # 1) compute outputs
                outputs: Dict[str, Any] = {}
                # keep pricing.tariff_total in sync (needed for premium_total)
                pricing.tariff_total = _computeTariffTotal(catalog, answers, pricing, params)
                pricing.premium_total = _computePremiumTotal(catalog, answers, pricing, params)
                for out in op.get("outputs", []):
                    fid = out["target_field_id"]
                    expr = out["value_expr"]
                    if expr == "computeTariffTotal()":
                        outputs[fid] = pricing.tariff_total
                    elif expr == "computePremiumTotal()":
                        outputs[fid] = pricing.premium_total
                    elif expr == "computeBreakdown()":
                        outputs[fid] = pricing.breakdown()
                    else:
                        outputs[fid] = safe_eval(expr, env, cfg)

                return pricing, outputs

            else:
                raise ValueError(f"Unknown pricing op: {opname}")

    return pricing, {}


def build_quote(catalog: Catalog, answers: Dict[str, Any]) -> Dict[str, Any]:
    params = build_params(catalog)
    computed = compute_computed(catalog, answers, params)
    pricing, outputs = execute_pricing(catalog, answers, computed, params)

    quote_id = str(uuid4())

    # Normalize outputs for JSON and UI:
    # - Keep API fields (premium_total, tariff_total, breakdown)
    # - Also expose schema output field_ids (FLD_*) so UI can render *_readonly fields
    normalized_outputs: Dict[str, Any] = {}
    for fid, val in outputs.items():
        if fid == "FLD_TARIFF_TOTAL":
            normalized_outputs[fid] = float(val)
        elif fid == "FLD_PREMIUM_TOTAL":
            normalized_outputs[fid] = int(val)
        else:
            normalized_outputs[fid] = val

    tariff_total = pricing.tariff_total
    premium_total = pricing.premium_total

    return {
        "quoteId": quote_id,
        "currency": catalog.currency(),
        "premium_total": premium_total,
        "tariff_total": float(tariff_total),
        "breakdown": pricing.breakdown(),
        "computed": computed,
        "validatedAnswers": answers,
        **normalized_outputs,
        "warnings": [],
    }
