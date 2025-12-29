from __future__ import annotations

import io
from typing import Any, Dict, List

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.graphics.shapes import Circle, Drawing, Polygon
from reportlab.lib import colors

from app.services.schema_loader import Catalog


def _label_for_item(catalog: Catalog, dict_id: str, item_id: str) -> str:
    item = catalog.dictionary_item_by_id(dict_id, item_id)
    return item.get("label") if item else item_id


def _collect_selected_risks(answers: Dict[str, Any]) -> List[str]:
    fields = [
        "FLD_RISKS_SLED",
        "FLD_RISKS_REINDEER",
        "FLD_RISKS_BAG",
        "FLD_RISKS_ELVES",
        "FLD_RISKS_PROD_BREAK",
        "FLD_RISKS_TPL",
        "FLD_RISKS_FORCE_MAJEURE",
    ]
    out: List[str] = []
    seen = set()
    for f in fields:
        for rid in answers.get(f, []) or []:
            if rid not in seen:
                seen.add(rid)
                out.append(rid)
    return out


def draw_snowflake_stamp(canvas: Canvas, x: float, y: float, r: float) -> None:
    """
    Векторная печать-снежинка (без внешних изображений).

    Требование ТЗ: "выглядит как печать/штамп".
    Реализация: двойное кольцо, пунктирный внешний контур, "зерно" по окружности,
    снежинка в центре и читаемая надпись.
    """
    import math

    canvas.saveState()

    stroke = colors.HexColor("#2563EB")
    canvas.setStrokeColor(stroke)
    canvas.setFillColor(stroke)

    # Outer ring (dashed) + inner ring (solid)
    canvas.setLineWidth(1.25)
    canvas.setDash(3, 2)
    canvas.circle(x, y, r, stroke=1, fill=0)
    canvas.setDash()  # reset
    canvas.setLineWidth(1.0)
    canvas.circle(x, y, r * 0.80, stroke=1, fill=0)

    # Small dots around ring ("ink grain")
    for i in range(24):
        ang = (2 * math.pi) * (i / 24.0)
        xd = x + (r * 0.90) * math.cos(ang)
        yd = y + (r * 0.90) * math.sin(ang)
        canvas.circle(xd, yd, r * 0.03, stroke=0, fill=1)

    # Snowflake: 8 arms with small branches (kept simple & stamp-like)
    canvas.setLineWidth(1.0)
    canvas.setDash()
    canvas.setStrokeColor(stroke)
    for k in range(8):
        ang = math.radians(k * 45)
        x1 = x + r * 0.55 * math.cos(ang)
        y1 = y + r * 0.55 * math.sin(ang)
        canvas.line(x, y, x1, y1)

        # branches
        bx = x + r * 0.35 * math.cos(ang)
        by = y + r * 0.35 * math.sin(ang)
        for sgn in (-1, 1):
            ang2 = ang + sgn * math.radians(28)
            x2 = bx + r * 0.18 * math.cos(ang2)
            y2 = by + r * 0.18 * math.sin(ang2)
            canvas.line(bx, by, x2, y2)

    # Inner small star
    for k in range(6):
        ang = math.radians(k * 60 + 15)
        x2 = x + r * 0.22 * math.cos(ang)
        y2 = y + r * 0.22 * math.sin(ang)
        canvas.line(x, y, x2, y2)

    canvas.restoreState()






def make_christmas_tree_drawing(width: float, height: float) -> Drawing:
    """Векторная новогодняя ёлочка (без внешних изображений)."""
    d = Drawing(width, height)

    # trunk
    trunk_w = width * 0.18
    trunk_h = height * 0.18
    trunk_x = (width - trunk_w) / 2
    d.add(
        Polygon(
            points=[
                trunk_x,
                0,
                trunk_x + trunk_w,
                0,
                trunk_x + trunk_w,
                trunk_h,
                trunk_x,
                trunk_h,
            ],
            fillColor=colors.HexColor("#8B5A2B"),
            strokeColor=None,
        )
    )

    # three green layers
    def tri(y0: float, w: float, h: float) -> None:
        d.add(
            Polygon(
                points=[
                    width / 2,
                    y0 + h,
                    (width - w) / 2,
                    y0,
                    (width + w) / 2,
                    y0,
                ],
                fillColor=colors.HexColor("#16A34A"),
                strokeColor=colors.HexColor("#15803D"),
                strokeWidth=1,
            )
        )

    tri(trunk_h + height * 0.02, width * 0.95, height * 0.35)
    tri(trunk_h + height * 0.20, width * 0.75, height * 0.32)
    tri(trunk_h + height * 0.36, width * 0.55, height * 0.28)

    # star
    d.add(
        Circle(
            width / 2,
            trunk_h + height * 0.68,
            height * 0.035,
            fillColor=colors.HexColor("#FBBF24"),
            strokeColor=None,
        )
    )

    # ornaments
    ornaments = [
        (0.35, 0.52, "#EF4444"),
        (0.65, 0.50, "#3B82F6"),
        (0.42, 0.38, "#F59E0B"),
        (0.58, 0.34, "#A855F7"),
        (0.50, 0.25, "#22C55E"),
    ]
    for ox, oy, col in ornaments:
        d.add(
            Circle(
                width * ox,
                trunk_h + height * oy,
                height * 0.03,
                fillColor=colors.HexColor(col),
                strokeColor=colors.white,
                strokeWidth=0.5,
            )
        )

    # garland stripe
    d.add(
        Polygon(
            points=[
                width * 0.25,
                trunk_h + height * 0.46,
                width * 0.75,
                trunk_h + height * 0.43,
                width * 0.75,
                trunk_h + height * 0.45,
                width * 0.25,
                trunk_h + height * 0.48,
            ],
            fillColor=colors.HexColor("#FDE68A"),
            strokeColor=None,
        )
    )

    return d





def _ensure_cyrillic_fonts_registered() -> None:
    """Register bundled DejaVu fonts so Cyrillic text works in PDF.

    ReportLab's built-in Type1 fonts (Helvetica, Times, Courier) can't encode Cyrillic,
    so any Russian text would crash with UnicodeEncodeError unless we use a TTF font.
    """
    try:
        pdfmetrics.getFont("DejaVuSans")
        pdfmetrics.getFont("DejaVuSans-Bold")
        return
    except Exception:
        pass

    base_dir = Path(__file__).resolve().parents[1]  # app/
    font_dir = base_dir / "static" / "fonts"
    regular = font_dir / "DejaVuSans.ttf"
    bold = font_dir / "DejaVuSans-Bold.ttf"
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(regular)))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(bold)))
    registerFontFamily("DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold")


def build_policy_pdf(
    catalog: Catalog, *, answers: Dict[str, Any], policy_number: str, issued_at_utc: str
) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    styles = getSampleStyleSheet()
    _ensure_cyrillic_fonts_registered()
    for _s in styles.byName.values():
        _s.fontName = "DejaVuSans"
        if hasattr(_s, "bulletFontName"):
            _s.bulletFontName = "DejaVuSans"
    story: List[Any] = []

    # 1) Header
    story.append(Paragraph('АО "СОГАЗ"', styles["Normal"]))
    story.append(Paragraph(f"Полис № {policy_number}", styles["Normal"]))
    story.append(Paragraph(f"Дата оформления (UTC): {issued_at_utc}", styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    # 2) Title
    story.append(
        Paragraph("<b>Полис Новогоднего страхования деятельности Деда Мороза</b>", styles["Title"])
    )
    tree = make_christmas_tree_drawing(36 * mm, 42 * mm)
    tree.hAlign = "CENTER"
    story.append(tree)
    story.append(Spacer(1, 6 * mm))

    # 3) Parties
    story.append(
        Paragraph('Договор заключён между АО "СОГАЗ" и Дедом Морозом.', styles["Normal"])
    )
    story.append(Spacer(1, 4 * mm))

    # 4) Insured block
    story.append(Paragraph("<b>Что застраховано</b>", styles["Heading2"]))

    objs = answers.get("FLD_OBJECTS_SELECTED", []) or []
    obj_labels = (
        ", ".join(_label_for_item(catalog, "DICT_INSURANCE_OBJECTS", oid) for oid in objs) or "—"
    )
    story.append(Paragraph(f"Выбранные объекты: {obj_labels}", styles["Normal"]))

    # Details from STEP_02 & STEP_03 (only those present)
    def add_if_present(fid: str) -> None:
        if fid in answers and answers[fid] is not None and answers[fid] != "":
            field = catalog.field_by_id(fid)
            story.append(Paragraph(f"{field.get('label')}: {answers[fid]}", styles["Normal"]))

    for fid in [
        "FLD_SANTA_AGE",
        "FLD_SANTA_WEIGHT",
        "FLD_SANTA_WAIST",
        "FLD_SLED_TYPE",
        "FLD_BAG_TYPE",
        "FLD_REINDEER_COUNT",
        "FLD_REINDEER_FLAGS",
        "FLD_ELVES_COUNT",
        "FLD_ELVES_FLAGS",
        "FLD_PROD_BREAK_FLAGS",
        "FLD_TPL_PARKING",
        "FLD_INSURED_SUM",
        "FLD_DEDUCTIBLE",
        "FLD_COVERAGE_LIMIT",
    ]:
        if fid == "FLD_SLED_TYPE" and answers.get(fid):
            add_if_present(fid)
            story.append(
                Paragraph(
                    f"↳ {_label_for_item(catalog, 'DICT_SLED_TYPES', answers[fid])}",
                    styles["Normal"],
                )
            )
        elif fid == "FLD_BAG_TYPE" and answers.get(fid):
            add_if_present(fid)
            story.append(
                Paragraph(
                    f"↳ {_label_for_item(catalog, 'DICT_BAG_TYPES', answers[fid])}",
                    styles["Normal"],
                )
            )
        elif fid in {
            "FLD_REINDEER_FLAGS",
            "FLD_ELVES_FLAGS",
            "FLD_PROD_BREAK_FLAGS",
            "FLD_TPL_PARKING",
        }:
            if answers.get(fid):
                field = catalog.field_by_id(fid)
                dict_id = field.get("dictionary_id")
                labels = ", ".join(_label_for_item(catalog, dict_id, x) for x in answers[fid])
                story.append(Paragraph(f"{field.get('label')}: {labels}", styles["Normal"]))
        else:
            add_if_present(fid)

    risks = _collect_selected_risks(answers)
    risk_labels = ", ".join(_label_for_item(catalog, "DICT_RISKS", rid) for rid in risks) or "—"
    story.append(Paragraph(f"Выбранные риски: {risk_labels}", styles["Normal"]))

    pay_method = answers.get("FLD_PAYMENT_METHOD")
    pay_status = answers.get("FLD_PAYMENT_STATUS")
    if pay_method:
        story.append(
            Paragraph(
                f"Оплата: {_label_for_item(catalog, 'DICT_PAYMENT_METHODS', pay_method)} "
                f"(статус: {pay_status or '—'})",
                styles["Normal"],
            )
        )

    story.append(Spacer(1, 4 * mm))

    # 5) Exclusions
    story.append(Paragraph("<b>Что не застраховано</b>", styles["Heading2"]))
    exclusions = [
        "Самовольная парковка на балконе при наличии крыши.",
        "Простой из-за философских споров эльфов.",
        "Проникновение через окно при наличии дымохода.",
        "Потеря настроения из-за отсутствия снега.",
    ]
    for ex in exclusions:
        story.append(Paragraph(f"• {ex}", styles["Normal"]))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<b>Территория страхования</b>", styles["Heading2"]))
    story.append(Paragraph("Весь мир.", styles["Normal"]))
    story.append(Spacer(1, 12 * mm))

    # Signatures are drawn on the last page via onLaterPages
    def draw_signatures(c: Canvas, _doc: SimpleDocTemplate) -> None:
        width, _height = A4
        c.saveState()
        _ensure_cyrillic_fonts_registered()

        y = 32 * mm
        left_x = 20 * mm
        right_x = width - 90 * mm

        c.setFont("DejaVuSans-Bold", 11)
        c.drawString(left_x, y + 28, 'АО "СОГАЗ"')
        c.drawString(right_x, y + 28, "Дед Мороз")

        c.setLineWidth(1)
        c.line(left_x, y + 18, left_x + 70 * mm, y + 18)
        c.line(right_x, y + 18, right_x + 70 * mm, y + 18)

        # Печать-снежинка под названием компании (не перекрываем подпись/линию)
        draw_snowflake_stamp(c, left_x + 32 * mm, y + 2 * mm, 13 * mm)

        c.restoreState()


    doc.build(story, onFirstPage=draw_signatures, onLaterPages=draw_signatures)
    return buffer.getvalue()
