from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.templating import Jinja2Templates

from app.domain.errors import FieldValidationError
from app.services.contract import build_contract
from app.services.pdf import build_policy_pdf
from app.services.pricing import build_quote
from app.services.rules import clear_invisible_answers, compute_visibility
from app.services.schema_loader import load_catalog
from app.services.validation import validate_answers

templates = Jinja2Templates(directory="app/templates")
router = APIRouter(prefix="/ui", tags=["ui"])


# ---- session helpers (cookie-signed, so keep it small!) ----


def _session(request: Request) -> Dict[str, Any]:
    return request.session  # type: ignore[attr-defined]


def _get_answers(request: Request) -> Dict[str, Any]:
    return dict(_session(request).get("answers") or {})


def _set_answers(request: Request, answers: Dict[str, Any]) -> None:
    _session(request)["answers"] = answers


def _flash_errors_set(request: Request, errors: Dict[str, str]) -> None:
    _session(request)["flash_errors"] = errors


def _flash_errors_pop(request: Request) -> Optional[Dict[str, str]]:
    err = _session(request).get("flash_errors")
    if err:
        _session(request).pop("flash_errors", None)
        return dict(err)
    return None


def _get_policy_number(request: Request) -> Optional[str]:
    return _session(request).get("policy_number")


def _ensure_policy_number(request: Request, quote_id: str) -> str:
    pn = _get_policy_number(request)
    if pn:
        return pn
    pn = "NY-" + quote_id[:8].upper()
    _session(request)["policy_number"] = pn
    _session(request)["quote_id"] = quote_id
    return pn


def _get_issued_at(request: Request) -> Optional[str]:
    return _session(request).get("issued_at_utc")


def _ensure_issued_at(request: Request) -> str:
    ts = _get_issued_at(request)
    if ts:
        return ts
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _session(request)["issued_at_utc"] = ts
    return ts


# ---- wizard model ----


WIZARD_STEPS = [
    {"key": "conditions", "title": "Условия", "url": "/ui/conditions/step/1"},
    {"key": "risks", "title": "Риски", "url": "/ui/risks"},
    {"key": "calc", "title": "Калькулятор", "url": "/ui/calc"},
    {"key": "contacts", "title": "Контакты", "url": "/ui/contacts"},
    {"key": "payment", "title": "Оплата", "url": "/ui/payment"},
    {"key": "final", "title": "Финал", "url": "/ui/final"},
]


def _steps(active_key: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen_active = False
    for st in WIZARD_STEPS:
        key = st["key"]
        status = "todo"
        if key == active_key:
            status = "current"
            seen_active = True
        elif not seen_active:
            status = "done"
        out.append({**st, "status": status})
    return out


def _page_fields(catalog: Any, screen_id: str, step: str | None = None) -> List[Dict[str, Any]]:
    # Source of truth: schema.inventory.fields (filtered by screen_id + optional step)
    return catalog.fields_for_screen(screen_id, step=step)


def _apply_risk_category_gates(catalog: Catalog, answers: Dict[str, Any], visible: Dict[str, bool]) -> Dict[str, bool]:
    """Safety gating for risk groups based on DICT_RISK_CATEGORIES.

    The schema already contains visibility rules for risks. This function uses *only schema data*
    as an additional guard to avoid showing irrelevant risk sections.
    """
    selected = set((answers.get("FLD_OBJECTS_SELECTED") or []))
    has_all = "OBJ_ALL_RISKS" in selected

    try:
        cat_gate = {it["id"]: it.get("object_gate") for it in catalog.dictionary_items("DICT_RISK_CATEGORIES")}
    except Exception:
        return visible

    for f in catalog.fields_for_screen("SCR_03_RISKS"):
        fid = f["field_id"]
        df = f.get("dictionary_filter") or {}
        category_id = df.get("equals")
        gate = cat_gate.get(category_id)
        if gate:
            visible[fid] = bool(visible.get(fid, True) and (has_all or gate in selected))
    return visible




def _parse_form_for_fields(form: Dict[str, Any], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for f in fields:
        fid = f["field_id"]
        dt = f.get("data_type")

        if dt == "string[]":
            v = form.get(fid)
            if v is None:
                out[fid] = []
            elif isinstance(v, list):
                out[fid] = v
            else:
                out[fid] = [v]
            continue

        v = form.get(fid)
        if v is None or v == "":
            continue
        if dt == "int":
            out[fid] = int(v)
        else:
            out[fid] = v
    return out


def _render_screen(
    request: Request,
    *,
    screen_id: str,
    title: str,
    fields: List[Dict[str, Any]],
    visible: Dict[str, bool],
    errors: Dict[str, str] | None,
    back_url: str | None,
    next_label: str,
    active_step_key: str,
    info: str | None = None,
    show_pay_button: bool = False,
    quote: Optional[Dict[str, Any]] = None,
) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)

    # merge flash errors (from redirects)
    flash = _flash_errors_pop(request)
    if flash:
        errors = {**flash, **(errors or {})}

    # prepare view fields
    view_fields = []
    for f in fields:
        fid = f["field_id"]
        is_vis = visible.get(fid, True)
        if not is_vis:
            continue

        value = answers.get(fid)

        # options for dict-based components
        options = []
        dict_id = f.get("dictionary_id")
        if dict_id:
            items = list(catalog.dictionary_items(dict_id))
            df = f.get("dictionary_filter") or {}
            by = df.get("by")
            eq = df.get("equals")
            if by and eq is not None:
                items = [it for it in items if it.get(by) == eq]
            for it in items:
                options.append({"id": it["id"], "label": it.get("label", it["id"])})
        view_fields.append(
            {
                "field": f,
                "field_id": fid,
                "label": f.get("label") or fid,
                "component": f.get("component"),
                "data_type": f.get("data_type"),
                "required": bool(f.get("required")),
                "constraints": f.get("constraints") or {},
                "options": options,
                "value": value,
            }
        )

    # Error summary
    summary = []
    if errors:
        for fid, msg in errors.items():
            if any(vf["field_id"] == fid for vf in view_fields):
                summary.append({"field_id": fid, "message": msg})

    return templates.TemplateResponse(
        "screen.html",
        {
            "request": request,
            "title": title,
            "info": info,
            "fields": view_fields,
            "errors": errors or {},
            "summary": summary,
            "back_url": back_url,
            "next_label": next_label,
            "show_pay_button": show_pay_button,
            "steps": _steps(active_step_key),
            "active_step_key": active_step_key,
            "quote": quote or {},
        },
    )


# ---- root/start/reset ----


@router.get("/")
def ui_root(request: Request) -> HTMLResponse:
    # Landing page with product image + "Buy" CTA
    return templates.TemplateResponse("landing.html", {"request": request})


@router.get("/start")
def ui_start(request: Request) -> RedirectResponse:
    # стартовый экран убран — сразу начинаем мастер
    request.session.clear()
    request.session.setdefault("answers", {})
    return RedirectResponse(url="/ui/conditions/step/1", status_code=302)


@router.post("/reset")
def ui_reset(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/ui/conditions/step/1", status_code=302)


# ---- CONDITIONS: 3 steps ----


@router.get("/conditions/step/1")
def conditions_step1(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_01")
    vis = compute_visibility(catalog, answers, {})
    return _render_screen(
        request,
        screen_id="SCR_01_CONDITIONS",
        title="Условия страхования — шаг 1/3",
        fields=step_fields,
        visible=vis,
        errors=None,
        back_url=None,
        next_label="Дальше",
        active_step_key="conditions",
        info="Выберите, что страхуем. Можно несколько вариантов.",
    )


@router.post("/conditions/step/1")
async def conditions_step1_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)

    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_01")

    payload: Dict[str, Any] = {}
    for f in step_fields:
        fid = f["field_id"]
        payload[fid] = form.getlist(fid)

    answers.update(_parse_form_for_fields(payload, step_fields))
    vis = compute_visibility(catalog, answers, {})
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=False)
        _set_answers(request, validated)
        return RedirectResponse(url="/ui/conditions/step/2", status_code=303)
    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_01_CONDITIONS",
            title="Условия страхования — шаг 1/3",
            fields=step_fields,
            visible=vis,
            errors=e.field_errors,
            back_url=None,
            next_label="Дальше",
            active_step_key="conditions",
        )


@router.get("/conditions/step/2")
def conditions_step2(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)

    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_02")

    vis = compute_visibility(catalog, answers, {})
    return _render_screen(
        request,
        screen_id="SCR_01_CONDITIONS",
        title="Условия страхования — шаг 2/3",
        fields=step_fields,
        visible=vis,
        errors=None,
        back_url="/ui/conditions/step/1",
        next_label="Дальше",
        active_step_key="conditions",
        info="Заполните детали. Если блок не виден — значит, вы не выбрали соответствующий объект.",
    )


@router.post("/conditions/step/2")
async def conditions_step2_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)
    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_02")

    payload = {f["field_id"]: form.get(f["field_id"]) for f in step_fields}
    answers.update(_parse_form_for_fields(payload, step_fields))

    vis = compute_visibility(catalog, answers, {})
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=False)
        _set_answers(request, validated)
        return RedirectResponse(url="/ui/conditions/step/3", status_code=303)
    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_01_CONDITIONS",
            title="Условия страхования — шаг 2/3",
            fields=step_fields,
            visible=vis,
            errors=e.field_errors,
            back_url="/ui/conditions/step/1",
            next_label="Дальше",
            active_step_key="conditions",
        )


@router.get("/conditions/step/3")
def conditions_step3(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)

    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_03")

    vis = compute_visibility(catalog, answers, {})
    return _render_screen(
        request,
        screen_id="SCR_01_CONDITIONS",
        title="Условия страхования — шаг 3/3",
        fields=step_fields,
        visible=vis,
        errors=None,
        back_url="/ui/conditions/step/2",
        next_label="К рискам",
        active_step_key="conditions",
        info="Задайте сумму, франшизу и лимит покрытия.",
    )


@router.post("/conditions/step/3")
async def conditions_step3_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)

    step_fields = _page_fields(catalog, "SCR_01_CONDITIONS", step="STEP_03")

    payload = {f["field_id"]: form.get(f["field_id"]) for f in step_fields}
    answers.update(_parse_form_for_fields(payload, step_fields))

    vis = compute_visibility(catalog, answers, {})
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=False)
        _set_answers(request, validated)
        return RedirectResponse(url="/ui/risks", status_code=303)
    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_01_CONDITIONS",
            title="Условия страхования — шаг 3/3",
            fields=step_fields,
            visible=vis,
            errors=e.field_errors,
            back_url="/ui/conditions/step/2",
            next_label="К рискам",
            active_step_key="conditions",
        )


# ---- RISKS ----


@router.get("/risks")
def risks(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_03_RISKS")

    vis = _apply_risk_category_gates(catalog, answers, compute_visibility(catalog, answers, {}))
    return _render_screen(
        request,
        screen_id="SCR_03_RISKS",
        title="Риски",
        fields=fields,
        visible=vis,
        errors=None,
        back_url="/ui/conditions/step/3",
        next_label="К калькулятору",
        active_step_key="risks",
        info="Выберите риски. Можно несколько — чем больше рисков, тем больше премия (магия математики).",
    )


@router.post("/risks")
async def risks_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_03_RISKS")

    payload: Dict[str, Any] = {}
    for f in fields:
        fid = f["field_id"]
        payload[fid] = form.getlist(fid)

    answers.update(_parse_form_for_fields(payload, fields))
    vis = _apply_risk_category_gates(catalog, answers, compute_visibility(catalog, answers, {}))
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=False)
        _set_answers(request, validated)
        return RedirectResponse(url="/ui/calc", status_code=303)
    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_03_RISKS",
            title="Риски",
            fields=fields,
            visible=vis,
            errors=e.field_errors,
            back_url="/ui/conditions/step/3",
            next_label="К калькулятору",
            active_step_key="risks",
        )


# ---- CALC ----


@router.get("/calc")
def calc(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    vis = compute_visibility(catalog, answers, {})
    answers_clean = clear_invisible_answers(dict(answers), vis)

    errors: Dict[str, str] | None = None
    quote: Optional[Dict[str, Any]] = None
    try:
        validated = validate_answers(catalog, answers_clean, visible=vis, require_all_required=False)
        quote = build_quote(catalog, validated)
    except FieldValidationError as e:
        errors = e.field_errors

    fields = _page_fields(catalog, "SCR_04_CALC")
    return _render_screen(
        request,
        screen_id="SCR_04_CALC",
        title="Калькулятор",
        fields=fields,
        visible=vis,
        errors=errors,
        back_url="/ui/risks",
        next_label="К контактам",
        active_step_key="calc",
        info="Показываем расчёт. Если чего-то не хватает, вернитесь назад и заполните поля.",
        quote=quote,
    )


@router.post("/calc")
async def calc_post(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/ui/contacts", status_code=303)


# ---- CONTACTS ----


@router.get("/contacts")
def contacts(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_05_CONTACTS")
    vis = compute_visibility(catalog, answers, {})
    return _render_screen(
        request,
        screen_id="SCR_05_CONTACTS",
        title="Контакты",
        fields=fields,
        visible=vis,
        errors=None,
        back_url="/ui/calc",
        next_label="К оплате",
        active_step_key="contacts",
        info="Кому отдаём полис (и кому доверяем новогоднюю магию).",
    )


@router.post("/contacts")
async def contacts_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_05_CONTACTS")

    payload = {f["field_id"]: form.get(f["field_id"]) for f in fields}
    answers.update(_parse_form_for_fields(payload, fields))
    vis = compute_visibility(catalog, answers, {})
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=False)
        _set_answers(request, validated)
        return RedirectResponse(url="/ui/payment", status_code=303)
    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_05_CONTACTS",
            title="Контакты",
            fields=fields,
            visible=vis,
            errors=e.field_errors,
            back_url="/ui/calc",
            next_label="К оплате",
            active_step_key="contacts",
        )


# ---- PAYMENT ----


@router.get("/payment")
def payment(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_06_PAYMENT")
    vis = compute_visibility(catalog, answers, {})
    return _render_screen(
        request,
        screen_id="SCR_06_PAYMENT",
        title="Оплата",
        fields=fields,
        visible=vis,
        errors=None,
        back_url="/ui/contacts",
        next_label="Финал",
        active_step_key="payment",
        show_pay_button=True,
        info="Выберите способ оплаты и нажмите «Оплатить».",
    )


@router.post("/payment")
async def payment_post(request: Request) -> Response:
    catalog = load_catalog()
    form = await request.form()
    answers = _get_answers(request)
    fields = _page_fields(catalog, "SCR_06_PAYMENT")

    action = form.get("action")
    if action is None or str(action).strip() == "":
        action = "ACT_PAY"

    payload = {f["field_id"]: form.get(f["field_id"]) for f in fields}
    answers.update(_parse_form_for_fields(payload, fields))

    vis = compute_visibility(catalog, answers, {})
    answers = clear_invisible_answers(answers, vis)

    try:
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=True)

        # execute payment effects strictly from schema actions/effects
        actions = catalog.actions()
        act = next((a for a in actions if a.get("action_id") == action), None)
        if act:
            for eff in act.get("effects") or []:
                if eff.get("op") == "set_answer":
                    # most effects in schema are constants like "PAID"
                    tgt = eff.get("target_field_id")
                    if tgt:
                        if "value" in eff:
                            answers[tgt] = eff["value"]
                        elif "value_expr" in eff:
                            # for this demo: value_expr is expected to be a constant (e.g. 'PAID')
                            answers[tgt] = str(eff["value_expr"]).strip("'\"")
                elif eff.get("op") == "set_policy_status":
                    request.session["policy_status"] = str(eff.get("value", "PAID"))

        request.session.setdefault("policy_status", "PAID")
        _set_answers(request, answers)

        # compute quote id for stable policy number + issued timestamp
        quote = build_quote(catalog, validated)
        _ensure_policy_number(request, quote["quoteId"])
        _ensure_issued_at(request)

        return RedirectResponse(url="/ui/final", status_code=303)

    except FieldValidationError as e:
        return _render_screen(
            request,
            screen_id="SCR_06_PAYMENT",
            title="Оплата",
            fields=fields,
            visible=vis,
            errors=e.field_errors,
            back_url="/ui/contacts",
            next_label="Финал",
            active_step_key="payment",
            show_pay_button=True,
        )


# ---- FINAL + downloads ----


@router.get("/final")
def final(request: Request) -> HTMLResponse:
    catalog = load_catalog()
    answers = _get_answers(request)
    policy_status = request.session.get("policy_status", "DRAFT")
    policy_number = request.session.get("policy_number")
    issued_at = request.session.get("issued_at_utc")

    quote: Optional[Dict[str, Any]] = None
    errors: Optional[str] = None

    # Try to recompute quote for display (do not store it in session!)
    try:
        vis = compute_visibility(catalog, answers, {})
        answers_clean = clear_invisible_answers(dict(answers), vis)
        validated = validate_answers(catalog, answers_clean, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        if not policy_number:
            policy_number = _ensure_policy_number(request, quote["quoteId"])
        if not issued_at:
            issued_at = _ensure_issued_at(request)
    except FieldValidationError:
        errors = "Не хватает данных для выпуска полиса. Вернитесь на шаг оплаты и заполните обязательные поля."
    except Exception:
        errors = "Что-то пошло не так. Попробуйте пройти шаг оплаты ещё раз."

    return templates.TemplateResponse(
        "final.html",
        {
            "request": request,
            "steps": _steps("final"),
            "active_step_key": "final",
            "policy_status": policy_status,
            "policy_number": policy_number,
            "issued_at": issued_at,
            "quote": quote,
            "final_error": errors,
        },
    )


@router.get("/policy.pdf")
def ui_policy_pdf(request: Request) -> Response:
    catalog = load_catalog()
    answers = _get_answers(request)

    if request.session.get("policy_status") != "PAID":
        return RedirectResponse(url="/ui/payment", status_code=303)

    try:
        vis = compute_visibility(catalog, answers, {})
        answers = clear_invisible_answers(dict(answers), vis)
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        pn = _ensure_policy_number(request, quote["quoteId"])
        issued_at = _ensure_issued_at(request)
        pdf_bytes = build_policy_pdf(
            catalog,
            answers=validated,
            policy_number=pn,
            issued_at_utc=issued_at,
        )
        return Response(content=pdf_bytes, media_type="application/pdf")
    except FieldValidationError as e:
        _flash_errors_set(request, e.field_errors)
        return RedirectResponse(url="/ui/payment", status_code=303)


@router.get("/policy.contract")
def ui_policy_contract(request: Request) -> JSONResponse:
    catalog = load_catalog()
    answers = _get_answers(request)

    if request.session.get("policy_status") != "PAID":
        return RedirectResponse(url="/ui/payment", status_code=303)  # type: ignore[return-value]

    try:
        vis = compute_visibility(catalog, answers, {})
        answers = clear_invisible_answers(dict(answers), vis)
        validated = validate_answers(catalog, answers, visible=vis, require_all_required=True)
        quote = build_quote(catalog, validated)
        pn = _ensure_policy_number(request, quote["quoteId"])
        issued_at = _ensure_issued_at(request)
        contract = build_contract(
            catalog,
            answers=validated,
            quote_id=quote["quoteId"],
            policy_number=pn,
            issued_at_utc=issued_at,
            premium_total=quote["premium_total"],
            tariff_total=quote["tariff_total"],
        )
        return JSONResponse(contract)
    except FieldValidationError as e:
        _flash_errors_set(request, e.field_errors)
        return RedirectResponse(url="/ui/payment", status_code=303)  # type: ignore[return-value]
