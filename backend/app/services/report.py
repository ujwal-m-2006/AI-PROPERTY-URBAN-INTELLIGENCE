"""Module 28 — 360° Property Intelligence Report (PDF).

Assembles the sections the platform can actually populate, and prints the rest
as UNAVAILABLE with the reason. The section list is fixed: a missing section is
shown as missing rather than dropped, so the reader can see the shape of what
was not knowable.

Design rules, which are the point of the document:

  * Every value carries its method — VERIFIED / ML PREDICTION / DATA-DRIVEN
    SCORE / RULE / UNAVAILABLE.
  * The provenance appendix lists every source behind the report.
  * The disclaimer block is not optional and cannot be suppressed by a caller.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core import disclaimers as D

NAVY = colors.HexColor("#1B365D")
ACCENT = colors.HexColor("#C2703A")
INK = colors.HexColor("#1F2430")
MUTED = colors.HexColor("#5C6675")
LINE = colors.HexColor("#D6DCE5")
PANEL = colors.HexColor("#F4F6F9")

# Kept as plain hex strings: reportlab's inline <font color="..."> markup needs
# a "#RRGGBB" literal, not a Color object.
METHOD_COLOURS = {
    "VERIFIED": "#1B7F3B",
    "ML PREDICTION": "#1B7F3B",
    "DATA-DRIVEN SCORE": "#B57200",
    "COMPOSITE": "#6D4E9E",
    "RULE": "#5C6675",
    "GIS": "#1B365D",
    "UNAVAILABLE": "#8A94A3",
}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=19, textColor=NAVY, spaceAfter=2,
                                alignment=TA_LEFT),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontName="Helvetica",
                              fontSize=10.5, textColor=ACCENT, spaceAfter=10),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontName="Helvetica-Bold",
                            fontSize=11.5, textColor=NAVY, spaceBefore=11,
                            spaceAfter=5),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.2, textColor=INK, leading=12.6),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontName="Helvetica",
                                fontSize=8, textColor=MUTED, leading=10.6),
        "warn": ParagraphStyle("w", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.6, textColor=colors.HexColor("#7A1414"),
                               leading=11.4),
    }


def _kv_table(rows: list[tuple[str, str, str]], st) -> Table:
    """Label / value / method table. Method is always shown."""
    data = [[Paragraph("<b>Item</b>", st["small"]),
             Paragraph("<b>Value</b>", st["small"]),
             Paragraph("<b>Method</b>", st["small"])]]
    styles = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for i, (label, value, method) in enumerate(rows, start=1):
        colour = METHOD_COLOURS.get(method, "#5C6675")
        data.append([
            Paragraph(label, st["body"]),
            Paragraph(value if value else "<i>Data unavailable</i>", st["body"]),
            Paragraph(f'<font color="{colour}"><b>{method}</b></font>',
                      st["small"]),
        ])
        if method == "UNAVAILABLE":
            styles.append(("BACKGROUND", (0, i), (-1, i), PANEL))

    t = Table(data, colWidths=[52 * mm, 78 * mm, 35 * mm], repeatRows=1)
    t.setStyle(TableStyle(styles))
    return t


def _header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(18 * mm, A4[1] - 8 * mm,
                      "360 PROPERTY INTELLIGENCE REPORT")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 8 * mm,
                           "Research prototype - not an official record")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18 * mm, 10 * mm,
                      "Decision support only. Does not replace legal, statutory "
                      "or professional verification.")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build(payload: dict[str, Any]) -> bytes:
    """Render the report. `payload` is assembled by the API layer."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="360 Property Intelligence Report",
        author="Property & Urban Intelligence Platform",
    )

    city = payload.get("city", {})
    generated = datetime.now(UTC).strftime("%d %B %Y, %H:%M UTC")
    flow: list[Any] = []

    # ---- cover -------------------------------------------------------
    flow.append(Paragraph("360° Property Intelligence Report", st["title"]))
    flow.append(Paragraph(
        f"{city.get('name', 'Unknown city')} &nbsp;·&nbsp; generated {generated}",
        st["sub"]))
    flow.append(HRFlowable(width="100%", color=ACCENT, thickness=1.4,
                           spaceAfter=9))

    summary = payload.get("summary", {})
    flow.append(Paragraph("1. Executive summary", st["h"]))
    flow.append(Paragraph(summary.get("text", "No summary available."), st["body"]))
    flow.append(Spacer(1, 5))

    for section_no, (title, rows) in enumerate(payload.get("sections", []), start=2):
        block = [Paragraph(f"{section_no}. {title}", st["h"])]
        if rows:
            block.append(_kv_table(rows, st))
        else:
            block.append(Paragraph(
                "<i>No data available for this section.</i>", st["small"]))
        flow.append(KeepTogether(block))
        flow.append(Spacer(1, 3))

    # ---- caveats -----------------------------------------------------
    caveats = payload.get("caveats", [])
    if caveats:
        flow.append(PageBreak())
        flow.append(Paragraph("Limitations of this report", st["h"]))
        for c in caveats:
            flow.append(Paragraph(f"&bull; {c}", st["warn"]))
            flow.append(Spacer(1, 2.5))

    # ---- provenance ---------------------------------------------------
    sources = payload.get("sources", [])
    if sources:
        flow.append(Paragraph("Source list", st["h"]))
        data = [[Paragraph("<b>Source</b>", st["small"]),
                 Paragraph("<b>Tier</b>", st["small"]),
                 Paragraph("<b>Licence / note</b>", st["small"])]]
        for s in sources:
            data.append([
                Paragraph(s.get("name", ""), st["small"]),
                Paragraph(s.get("tier", ""), st["small"]),
                Paragraph(s.get("licence", ""), st["small"]),
            ])
        t = Table(data, colWidths=[62 * mm, 16 * mm, 87 * mm], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        flow.append(t)

    # ---- disclaimer (mandatory) ---------------------------------------
    flow.append(Spacer(1, 9))
    flow.append(Paragraph("Disclaimer", st["h"]))
    flow.append(Paragraph(D.PLATFORM_NATURE, st["warn"]))
    flow.append(Spacer(1, 3))
    flow.append(Paragraph(D.RECORDS_NOT_AUTOMATED, st["warn"]))
    flow.append(Spacer(1, 3))
    flow.append(Paragraph(D.KHATA_IS_NOT_TITLE, st["warn"]))
    flow.append(Spacer(1, 3))
    flow.append(Paragraph(
        "This report does not replace: " + "; ".join(D.DOES_NOT_REPLACE) + ".",
        st["warn"]))

    doc.build(flow, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
