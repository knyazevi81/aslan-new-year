from __future__ import annotations

from typing import Any, Dict, List

from app.services.schema_loader import Catalog

VC_CONTEXT = "https://www.w3.org/2018/credentials/v1"


def _label_for_item(catalog: Catalog, dict_id: str, item_id: str) -> str:
    item = catalog.dictionary_item_by_id(dict_id, item_id)
    return item.get("label") if item else item_id


def build_contract(
    catalog: Catalog,
    *,
    answers: Dict[str, Any],
    quote_id: str,
    policy_number: str,
    issued_at_utc: str,
    premium_total: int,
    tariff_total: float,
) -> Dict[str, Any]:
    app_context = {
        "@vocab": "https://example.invalid/santa-insurance#",
        "quoteId": "quoteId",
        "policyNumber": "policyNumber",
        "currency": "currency",
        "premium_total": "premium_total",
        "tariff_total": "tariff_total",
        "holder": "holder",
        "selections": "selections",
    }

    objects = answers.get("FLD_OBJECTS_SELECTED", []) or []
    risks_fields = [
        "FLD_RISKS_SLED",
        "FLD_RISKS_REINDEER",
        "FLD_RISKS_BAG",
        "FLD_RISKS_ELVES",
        "FLD_RISKS_PROD_BREAK",
        "FLD_RISKS_TPL",
        "FLD_RISKS_FORCE_MAJEURE",
    ]
    risks: List[str] = []
    seen = set()
    for f in risks_fields:
        for rid in answers.get(f, []) or []:
            if rid not in seen:
                seen.add(rid)
                risks.append(rid)

    selections = {
        "objects": [
            {"id": oid, "label": _label_for_item(catalog, "DICT_INSURANCE_OBJECTS", oid)}
            for oid in objects
        ],
        "risks": [
            {"id": rid, "label": _label_for_item(catalog, "DICT_RISKS", rid)} for rid in risks
        ],
        "conditions": {
            "insured_sum": answers.get("FLD_INSURED_SUM"),
            "deductible": answers.get("FLD_DEDUCTIBLE"),
            "coverage_limit": answers.get("FLD_COVERAGE_LIMIT"),
        },
    }

    holder = {
        "full_name": answers.get("FLD_POLICYHOLDER_NAME"),
        "phone": answers.get("FLD_POLICYHOLDER_PHONE"),
        "email": answers.get("FLD_POLICYHOLDER_EMAIL"),
    }

    return {
        "@context": [VC_CONTEXT, app_context],
        "type": ["VerifiableCredential", "InsurancePolicyCredential"],
        "issuer": 'АО "СОГАЗ" (demo)',
        "issuanceDate": issued_at_utc,
        "credentialSubject": {
            "quoteId": quote_id,
            "policyNumber": policy_number,
            "currency": catalog.currency(),
            "premium_total": premium_total,
            "tariff_total": tariff_total,
            "holder": holder,
            "selections": selections,
        },
    }
