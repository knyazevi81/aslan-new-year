from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.domain.errors import FieldValidationError
from app.services.contract import build_contract
from app.services.pdf import build_policy_pdf
from app.services.pricing import build_quote
from app.services.rules import clear_invisible_answers, compute_visibility
from app.services.schema_loader import load_catalog
from app.services.validation import validate_answers

router = APIRouter(prefix="/api", tags=["api"])


def _req_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    return load_catalog().raw


@router.post("/quote")
async def post_quote(payload: Dict[str, Any], request: Request) -> JSONResponse:
    catalog = load_catalog()
    try:
        answers_in = payload.get("answers") or {}
        # visibility: clear invisible data before validate+quote
        computed_stub: Dict[str, Any] = {}
        vis = compute_visibility(catalog, answers_in, computed_stub)
        answers_in = clear_invisible_answers(answers_in, vis)
        validated = validate_answers(catalog, answers_in, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        return JSONResponse(quote)
    except FieldValidationError as e:
        return JSONResponse(status_code=400, content=e.to_dict(_req_id(request)))
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={
                "title": "Internal error",
                "detail": "Внутренняя ошибка. Эльфы уже бегут чинить.",
                "requestId": _req_id(request),
            },
        )


@router.post("/policy/pdf")
async def post_policy_pdf(payload: Dict[str, Any], request: Request) -> Response:
    catalog = load_catalog()
    try:
        answers_in = payload.get("answers") or {}
        vis = compute_visibility(catalog, answers_in, {})
        answers_in = clear_invisible_answers(answers_in, vis)
        validated = validate_answers(catalog, answers_in, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        policy_number = "NY-" + quote["quoteId"][:8].upper()
        issued_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        pdf_bytes = build_policy_pdf(
            catalog,
            answers=validated,
            policy_number=policy_number,
            issued_at_utc=issued_at,
        )
        return Response(content=pdf_bytes, media_type="application/pdf")
    except FieldValidationError as e:
        return JSONResponse(status_code=400, content=e.to_dict(_req_id(request)))
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={
                "title": "Internal error",
                "detail": "Внутренняя ошибка. Эльфы уже бегут чинить.",
                "requestId": _req_id(request),
            },
        )


@router.post("/policy/contract")
async def post_policy_contract(payload: Dict[str, Any], request: Request) -> JSONResponse:
    catalog = load_catalog()
    try:
        answers_in = payload.get("answers") or {}
        vis = compute_visibility(catalog, answers_in, {})
        answers_in = clear_invisible_answers(answers_in, vis)
        validated = validate_answers(catalog, answers_in, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        policy_number = "NY-" + quote["quoteId"][:8].upper()
        issued_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        contract = build_contract(
            catalog,
            answers=validated,
            quote_id=quote["quoteId"],
            policy_number=policy_number,
            issued_at_utc=issued_at,
            premium_total=quote["premium_total"],
            tariff_total=quote["tariff_total"],
        )
        return JSONResponse(contract)
    except FieldValidationError as e:
        return JSONResponse(status_code=400, content=e.to_dict(_req_id(request)))
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={
                "title": "Internal error",
                "detail": "Внутренняя ошибка. Эльфы уже бегут чинить.",
                "requestId": _req_id(request),
            },
        )
