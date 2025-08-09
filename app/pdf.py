from __future__ import annotations

import io
from typing import Optional

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def _coerce_price(value: Optional[str]) -> float:
    if not value:
        return 0.0
    s = str(value)
    # Remove common currency tokens
    for tok in ["Rs", "$", "USD", "LKR", ","]:
        s = s.replace(tok, "")
    try:
        return float(s.strip())
    except Exception:
        return 0.0


def build_budget_pdf(bom_df: pd.DataFrame, results_df: pd.DataFrame) -> bytes:
    # Merge to get quantities alongside matches
    df = results_df.copy()
    bom_view = bom_df.copy()
    bom_view["_join_key"] = bom_view["Part_Name"].fillna("")
    df["_join_key"] = df["BOM Part Name"].fillna("")
    merged = pd.merge(df, bom_view[["_join_key", "Quantity"]], on="_join_key", how="left")
    merged["Quantity"] = merged["Quantity"].fillna(0).astype(int)

    merged["Unit Price"] = merged["Price"].apply(_coerce_price)
    merged["Line Total"] = merged["Unit Price"] * merged["Quantity"]
    total_budget = float(merged["Line Total"].sum())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story = []

    # Header with version
    story.append(Paragraph("BOM Budget Summary (v1.0)", styles["Title"]))
    story.append(Spacer(1, 6))

    # Summary table with Total Price
    summary_data = [["Total Price", f"{total_budget:,.2f}"]]
    summary_table = Table(summary_data, hAlign='LEFT')
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('INNERGRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('BOX', (0,0), (-1,-1), 0.5, colors.grey),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    columns = [
        "BOM Part Name",
        "Found Part Name",
        "Supplier",
        "Quantity",
        "Price",
        "Unit Price",
        "Line Total",
        "Purchase Link",
    ]
    table_data = [columns]
    for _, r in merged.iterrows():
        table_data.append([
            str(r.get("BOM Part Name", "")),
            str(r.get("Found Part Name", "")),
            str(r.get("Supplier", "")),
            int(r.get("Quantity", 0)),
            str(r.get("Price", "")),
            f"{float(r.get('Unit Price', 0.0)):.2f}",
            f"{float(r.get('Line Total', 0.0)):.2f}",
            str(r.get("Purchase Link", "")),
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightblue),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 10),
        ('GRID', (0,0), (-1,-1), 0.25, colors.grey),
        ('ALIGN', (3,1), (3,-1), 'RIGHT'),
        ('ALIGN', (5,1), (6,-1), 'RIGHT'),
    ]))

    # Scale the table to available width
    avail_width = A4[0] - (doc.leftMargin + doc.rightMargin)
    # Measure column count and derive widths proportionally
    col_count = len(columns)
    col_width = avail_width / col_count
    table._argW = [col_width] * col_count

    story.append(table)

    doc.build(story)
    buf.seek(0)
    return buf.read()