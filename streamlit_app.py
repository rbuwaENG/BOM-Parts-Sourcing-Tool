import os
import io
import json
import time
from datetime import datetime
from typing import List, Dict, Any

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.db import get_session, ensure_db_initialized
from app.models import Part, Supplier, SupplierRule
from app.utils import (
    read_bom_file,
    validate_bom_columns,
    initialize_database_with_sample_data,
    dataframe_to_download_bytes,
)
from app.matching import find_best_matches_for_bom
from app.scheduler import get_last_update_time, trigger_background_refresh

APP_TITLE = "BOM Sourcing & Suggestion Platform"

st.set_page_config(page_title=APP_TITLE, layout="wide")

# Header
st.title(APP_TITLE)
st.caption("Find exact and alternative electronic parts across multiple suppliers.")

# Ensure DB initialized and seed sample data on first run
ensure_db_initialized()
initialize_database_with_sample_data()

# Sidebar controls
with st.sidebar:
    st.header("Options")
    min_similarity = st.slider("Minimum Similarity %", min_value=0, max_value=100, value=70, step=5)
    in_stock_only = st.checkbox("In-stock only", value=False)

    with get_session() as session:
        supplier_names = [s.name for s in session.query(Supplier).order_by(Supplier.name).all()]
    supplier_filter = st.multiselect("Suppliers", options=supplier_names, default=supplier_names)

    st.divider()
    st.subheader("Database")
    if st.button("Refresh Cached Data Now"):
        trigger_background_refresh()
        st.success("Background refresh triggered.")

    last_update = get_last_update_time()
    st.caption(f"Last Database Update: {last_update if last_update else 'Never'}")

# Section 1: BOM Upload
st.subheader("📂 Upload Your BOM")
st.write("Accepted formats: CSV, Excel (.xlsx). Columns: Part_Number, Description, Quantity, Package, Voltage, Other_Specs")
col_a, col_b = st.columns([3, 1])
with col_a:
    uploaded_file = st.file_uploader("Choose a BOM file", type=["csv", "xlsx"], accept_multiple_files=False)
with col_b:
    st.download_button(
        label="Download Template",
        data=open("data/bom_template.csv", "rb").read(),
        file_name="bom_template.csv",
        mime="text/csv",
    )

if uploaded_file is not None:
    try:
        bom_df = read_bom_file(uploaded_file)
    except Exception as exc:
        st.error(f"Failed to read BOM file: {exc}")
        st.stop()

    ok, missing = validate_bom_columns(bom_df.columns)
    if not ok:
        st.warning(f"Missing expected columns: {', '.join(missing)}")

    st.write("Preview of your uploaded BOM (first 100 rows):")
    st.dataframe(bom_df.head(100), use_container_width=True)

    st.caption(f"Active suppliers: {', '.join(supplier_filter) if supplier_filter else 'None'}")

    if st.button("Upload & Process"):
        with st.spinner("Processing your BOM... this may take a moment"):
            start = time.time()
            with get_session() as session:
                results_df, suggestions_map = find_best_matches_for_bom(
                    session=session,
                    bom_df=bom_df,
                    min_similarity=min_similarity,
                    in_stock_only=in_stock_only,
                    supplier_filter=supplier_filter,
                )
            elapsed = time.time() - start
        st.success(f"Processing done in {elapsed:.1f}s")

        # Color styling by similarity
        def similarity_color(val: Any) -> str:
            try:
                v = float(val)
            except Exception:
                return ""
            if v >= 100:
                return "background-color: #DCFCE7"
            if v >= 70:
                return "background-color: #FEF3C7"
            return "background-color: #FEE2E2"

        st.subheader("🔍 Available Matches")
        # Separate available results (where a match was found)
        available_df = results_df[results_df["Found Part Name"].notna()].copy()
        if not available_df.empty:
            st.dataframe(
                available_df.style.applymap(similarity_color, subset=["Similarity %"]),
                use_container_width=True,
                column_config={
                    "Image": st.column_config.ImageColumn("Image", help="Product image", width="small"),
                    "Datasheet Link": st.column_config.LinkColumn("Datasheet Link"),
                    "Purchase Link": st.column_config.LinkColumn("Purchase Link"),
                },
            )
        else:
            st.caption("No direct matches found above the similarity threshold.")

        # Download buttons
        csv_bytes = dataframe_to_download_bytes(results_df, kind="csv")
        xlsx_bytes = dataframe_to_download_bytes(results_df, kind="xlsx")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("⬇ Download CSV", data=csv_bytes, file_name="bom_results.csv", mime="text/csv")
        with col2:
            st.download_button("⬇ Download Excel", data=xlsx_bytes, file_name="bom_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Suggestions section: group unique alternatives across unmatched parts
        st.subheader("▼ Suggestions (Unique Alternatives)")
        # Flatten and deduplicate by (supplier, found_part_name, purchase_link)
        seen = set()
        unique_rows = []
        for _, suggestions in suggestions_map.items():
            for srow in suggestions:
                key = (srow.get("supplier"), srow.get("found_part_name"), srow.get("purchase_link"))
                if key in seen:
                    continue
                seen.add(key)
                unique_rows.append(srow)
        if unique_rows:
            suggestions_df = pd.DataFrame(unique_rows)
            # Order columns and rename
            if not suggestions_df.empty:
                suggestions_df = suggestions_df[[
                    "found_part_name",
                    "supplier",
                    "price",
                    "stock",
                    "image",
                    "datasheet_link",
                    "purchase_link",
                    "similarity",
                ]]
                suggestions_df.rename(columns={
                    "found_part_name": "Found Part Name",
                    "supplier": "Supplier",
                    "price": "Price",
                    "stock": "Stock Availability",
                    "image": "Image",
                    "datasheet_link": "Datasheet Link",
                    "purchase_link": "Purchase Link",
                    "similarity": "Similarity %",
                }, inplace=True)
            st.dataframe(
                suggestions_df.style.applymap(similarity_color, subset=["Similarity %"]),
                use_container_width=True,
                column_config={
                    "Image": st.column_config.ImageColumn("Image", help="Product image", width="small"),
                    "Datasheet Link": st.column_config.LinkColumn("Datasheet Link"),
                    "Purchase Link": st.column_config.LinkColumn("Purchase Link"),
                },
            )
        else:
            st.caption("No alternative suggestions available.")

# Section: Add new supplier
st.divider()
st.subheader("➕ Add New Supplier")
with st.form("add_supplier_form", clear_on_submit=False):
    name = st.text_input("Supplier Name")
    base_url = st.text_input("Shop Homepage URL")
    search_template = st.text_input("Product Search URL Template (use {query})")
    st.caption("Example: https://tronic.lk/?s={query}&post_type=product")
    auto_detect = st.checkbox("Attempt automatic HTML structure detection", value=True)

    submitted = st.form_submit_button("Save Supplier")
    if submitted:
        with get_session() as session:
            supplier = Supplier(name=name.strip(), base_url=base_url.strip() or None)
            session.add(supplier)
            session.flush()

            rule = SupplierRule(
                supplier_id=supplier.id,
                search_url_template=search_template.strip() if search_template else None,
            )
            session.add(rule)
            session.commit()
        st.success("Supplier saved. Go to 'Supplier Rules' page to customize selectors if auto-detect fails.")

# Footer
st.caption("Disclaimer: Prices and availability may change. Data is provided as-is.")