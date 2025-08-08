import json
import time
import pandas as pd
import streamlit as st

from app.db import get_session
from app.models import Supplier, Part
from app.scheduler import read_progress

st.set_page_config(page_title="Scraping Runner", layout="wide")
st.title("Scraping Runner & Monitor")

# Show live progress for all suppliers
progress_data = read_progress("all")  # optional aggregation key
with get_session() as session:
    suppliers = session.query(Supplier).order_by(Supplier.name).all()

rows = []
for s in suppliers:
    prog = read_progress(f"scrape:{s.name}")
    rows.append({
        "Supplier": s.name,
        "Status": prog.get("status", "idle"),
        "Progress %": prog.get("pct", 0.0),
        "Scraped": prog.get("scraped", 0),
        "Stored": prog.get("stored", 0),
    })

st.subheader("Live Progress")
st.dataframe(pd.DataFrame(rows), use_container_width=True)

# Per-supplier totals in DB
st.subheader("Totals in Database")
with get_session() as session:
    totals = []
    for s in suppliers:
        count = session.query(Part).filter(Part.supplier_id == s.id).count()
        totals.append({"Supplier": s.name, "Products in DB": count})
    st.dataframe(pd.DataFrame(totals), use_container_width=True)

st.info("This page updates when you refresh. For auto-refresh, enable Streamlit's rerun or add a timer.")