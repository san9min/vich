"""Generate examples/nimbus_storage_plan.pdf: a fictional 2-page product
guide used as vich's example fixture.

Entirely made up ("Nimbus Cloud" is not a real product) so it carries no
copyright/licensing concerns, while still exercising the layout elements
vich is meant to chunk well: headings, a pricing table, a boxed note, a
bulleted list, and a footnote.

Requires `pip install reportlab` (a docs-only tool, not a project
dependency). Re-run after editing this file to regenerate the PDF:

    python examples/generate_sample_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT_PATH = Path(__file__).parent / "nimbus_storage_plan.pdf"

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=20, spaceAfter=6)
disclaimer_style = ParagraphStyle(
    "Disclaimer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, spaceAfter=18
)
h2_style = ParagraphStyle("H2", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6)
h3_style = ParagraphStyle("H3", parent=styles["Heading3"], spaceBefore=8, spaceAfter=4)
body_style = ParagraphStyle("Body", parent=styles["BodyText"], spaceAfter=8, leading=14)
footnote_style = ParagraphStyle("Footnote", parent=styles["Normal"], fontSize=8, textColor=colors.grey)


def build() -> None:
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=LETTER,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
    )

    story = []

    # --- Page 1 ---
    story.append(Paragraph("Nimbus Cloud Storage Plan Guide", title_style))
    story.append(
        Paragraph(
            "This is a fictional product document created for demonstration "
            "purposes only. \"Nimbus Cloud\" is not a real product or company.",
            disclaimer_style,
        )
    )

    story.append(Paragraph("1. Plan Overview", h2_style))
    story.append(
        Paragraph(
            "Nimbus Cloud Storage is a subscription plan for backing up and "
            "syncing files across devices. Each plan includes encrypted "
            "storage, automatic versioning, and shared folder access. "
            "Plans renew monthly unless cancelled before the next billing date.",
            body_style,
        )
    )

    story.append(Paragraph("2. Pricing", h2_style))
    pricing_data = [
        ["Plan", "Monthly Fee", "Storage", "Support Level"],
        ["Starter", "$4.99", "100 GB", "Email"],
        ["Plus", "$9.99", "500 GB", "Email + Chat"],
        ["Pro", "$19.99", "2 TB", "Priority (24h)"],
        ["Team", "$49.99 / 5 seats", "10 TB shared", "Priority (4h)"],
    ]
    pricing_table = Table(pricing_data, hAlign="LEFT", colWidths=[1.1 * inch, 1.5 * inch, 1.3 * inch, 1.6 * inch])
    pricing_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b3a55")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f7")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(pricing_table)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Important Notes", h2_style))
    note_text = Paragraph(
        "<b>Note:</b> Prices exclude applicable taxes. Storage limits are "
        "shared across all devices linked to an account. Exceeding your "
        "plan's storage limit pauses new uploads until space is freed or "
        "the plan is upgraded.",
        body_style,
    )
    note_box = Table([[note_text]], colWidths=[5.5 * inch])
    note_box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#c9852b")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf3e3")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(note_box)

    story.append(PageBreak())

    # --- Page 2 ---
    story.append(Paragraph("3. Usage Limits", h2_style))
    story.append(Paragraph("Fair Use Policy", h3_style))
    story.append(
        ListFlowable(
            [
                ListItem(Paragraph("Maximum individual file size: 50 GB.", body_style)),
                ListItem(Paragraph("Maximum shared folder members: 20 accounts.", body_style)),
                ListItem(Paragraph("API requests are limited to 1,000 calls per hour per account.", body_style)),
                ListItem(Paragraph("Continuous automated uploads exceeding 500 GB/day may be throttled.", body_style)),
            ],
            bulletType="bullet",
        )
    )

    story.append(Paragraph("4. Cancellation &amp; Refunds", h2_style))
    story.append(
        Paragraph(
            "Plans can be cancelled at any time from account settings. "
            "Cancelling stops the next renewal charge; access continues "
            "until the end of the current billing period. Pro-rated "
            "refunds apply only within 14 days of the initial purchase.¹",
            body_style,
        )
    )
    story.append(Spacer(1, 40))
    story.append(
        Paragraph(
            "¹ Refunds are processed to the original payment method within 5–7 business days.",
            footnote_style,
        )
    )

    doc.build(story)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
