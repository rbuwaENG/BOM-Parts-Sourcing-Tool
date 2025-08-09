import os
import io
import json
import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd
# Ensure local package resolution
import bootstrap  # noqa: F401
import streamlit as st
from sqlalchemy.orm import Session

from app.db import get_session, ensure_db_initialized
from app.models import Part, Supplier, SupplierRule
from app.utils import (
    read_bom_file,
    validate_bom_columns,
    initialize_database_with_sample_data,
    dataframe_to_download_bytes,
    normalize_bom_columns,
)
from app.matching import find_best_matches_for_bom
from app.scheduler import get_last_update_time, write_progress, read_progress
from app.runner import run_all_scrapers

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
    last_update = get_last_update_time()
    st.caption(f"Last Database Update: {last_update if last_update else 'Never'}")
    if st.button("Refresh Database (Background)"):
        def _bg_refresh():
            with get_session() as session:
                write_progress("scrape:all", {"pct": 0.0, "scraped": 0, "stored": 0, "status": "running"})
                run_all_scrapers(session, progress_key="scrape:all", batch_size=500)
        threading.Thread(target=_bg_refresh, daemon=True).start()
        st.success("Refresh started. Check progress in the Suppliers & Scraping Runner tab.")

# Tabs for usability
tab_bom, tab_suppliers, tab_inventory = st.tabs(["📂 BOM", "🛠️ Suppliers & Scraping Runner", "📦 Inventory by Supplier"])

with tab_suppliers:
    st.subheader("Supplier Settings & Scraping")
    with get_session() as session:
        suppliers = session.query(Supplier).order_by(Supplier.name).all()
        supplier_rows = [{"id": s.id, "name": s.name, "is_active": s.is_active} for s in suppliers]

    add_expander = st.expander("➕ Add New Supplier", expanded=False)
    with add_expander:
        with st.form("add_supplier_form", clear_on_submit=True):
            new_name = st.text_input("Supplier Name", placeholder="Example: New Shop")
            new_base = st.text_input("Homepage URL", placeholder="https://example.com")
            new_search = st.text_input("Search URL Template (use {query})", placeholder="https://example.com/search?q={query}")
            new_enabled = st.checkbox("Enable scraper", value=True)
            new_sitemap = st.text_area("Optional Sitemap JSON", height=150)
            submitted = st.form_submit_button("Create Supplier")
            if submitted:
                if not new_name.strip():
                    st.error("Supplier name is required.")
                else:
                    with get_session() as session:
                        if session.query(Supplier).filter_by(name=new_name.strip()).first():
                            st.error("Supplier with this name already exists.")
                        else:
                            sup = Supplier(name=new_name.strip(), base_url=new_base.strip() or None)
                            session.add(sup)
                            session.flush()
                            rule = SupplierRule(
                                supplier_id=sup.id,
                                search_url_template=new_search.strip() or None,
                                sitemap_json=new_sitemap.strip() or None,
                                is_enabled=bool(new_enabled),
                            )
                            session.add(rule)
                            session.commit()
                            st.success("Supplier created.")

    st.markdown("---")

    sel_col2, sel_col3 = st.columns([1, 1])
    with sel_col2:
        run_all = st.button("Run All Scrapers (Background)")
    with sel_col3:
        refresh_progress = st.button("Refresh Progress")

    manage_expander = st.expander("✏️ Select & Manage Supplier", expanded=False)
    with manage_expander:
        with get_session() as session:
            suppliers = session.query(Supplier).order_by(Supplier.name).all()
            supplier_rows = [{"id": s.id, "name": s.name, "is_active": s.is_active} for s in suppliers]
        sel_name = st.selectbox("Select supplier", options=[s["name"] for s in supplier_rows] if supplier_rows else [])

        # Allow custom uploads for a supplier (pre-scraped list)
        custom_expander = st.expander("📥 Upload Custom Product List for Selected Supplier", expanded=False)
        with custom_expander:
            st.caption("Upload a CSV or Excel (.xlsx) with columns: Part_Number, Name, Description, Price, Stock, Datasheet, Purchase_Link, Image")
            custom_file = st.file_uploader("Custom Product File", type=["csv", "xlsx"], key="custom_csv")
            if custom_file is not None and sel_name:
                try:
                    # Robust read for CSV/Excel
                    if custom_file.name.lower().endswith(".csv"):
                        raw = custom_file.read()
                        df = None
                        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
                            try:
                                text = raw.decode(enc)
                                df = pd.read_csv(io.StringIO(text))
                                break
                            except Exception:
                                df = None
                        if df is None:
                            raise ValueError("Unable to decode CSV with common encodings")
                    else:
                        df = pd.read_excel(custom_file)
                    st.dataframe(df.head(50), use_container_width=True)
                    if st.button("Ingest Custom List"):
                        from app.utils import infer_custom_product_mapping, normalize_custom_records
                        mapping = infer_custom_product_mapping(df)
                        records = normalize_custom_records(df, mapping)
                        with get_session() as session:
                            sup = session.query(Supplier).filter_by(name=sel_name).first()
                            if not sup:
                                st.error("Selected supplier not found.")
                            else:
                                to_insert = []
                                for rec in records:
                                    part = Part(
                                        supplier_id=sup.id,
                                        part_number=rec.get("part_number"),
                                        name=rec.get("name"),
                                        description=rec.get("description"),
                                        stock=rec.get("stock"),
                                        price_tiers_json=json.dumps([{ "qty": 1, "price": rec.get("price") or "" }]),
                                        datasheet_url=rec.get("datasheet"),
                                        purchase_url=rec.get("purchase_link"),
                                        image_url=rec.get("image"),
                                    )
                                    to_insert.append(part)
                                if to_insert:
                                    session.bulk_save_objects(to_insert, return_defaults=False)
                                    session.commit()
                                    st.success(f"Ingested {len(to_insert)} products into {sel_name}.")
                except Exception as exc:
                    st.error(f"Failed to read custom CSV: {exc}")

        if sel_name:
            selected = next(s for s in supplier_rows if s["name"] == sel_name)
            with get_session() as session:
                supplier = session.get(Supplier, selected["id"])  # type: ignore[arg-type]
                rule = session.query(SupplierRule).filter_by(supplier_id=supplier.id).first()

            col1, col2 = st.columns(2)
            with col1:
                is_active = st.toggle("Supplier active", value=bool(supplier.is_active))
            with col2:
                rule_enabled = st.toggle("Scraper enabled", value=bool(rule.is_enabled) if rule else True)

            st.markdown("Sitemap JSON (used by scraper):")
            initial_json = rule.sitemap_json if rule and rule.sitemap_json else ""
            new_json = st.text_area("Sitemap JSON", value=initial_json, height=180, placeholder="Paste JSON here")

            btn_col1, btn_col2 = st.columns([1,1])
            with btn_col1:
                if st.button("Save Supplier Settings"):
                    with get_session() as session:
                        s = session.get(Supplier, supplier.id)
                        s.is_active = is_active
                        r = session.query(SupplierRule).filter_by(supplier_id=s.id).first()
                        if not r:
                            r = SupplierRule(supplier_id=s.id)
                            session.add(r)
                        r.is_enabled = rule_enabled
                        r.sitemap_json = new_json.strip() or None
                        session.commit()
                    st.success("Saved supplier and rule settings.")
            with btn_col2:
                st.markdown("**Danger Zone**")
                del_confirm = st.checkbox("I understand this will delete the supplier and all related data.")
                if st.button("Delete Supplier"):
                    if not del_confirm:
                        st.warning("Please confirm deletion by ticking the checkbox.")
                    else:
                        with get_session() as session:
                            sup = session.get(Supplier, supplier.id)
                            if sup:
                                session.delete(sup)
                                session.commit()
                                st.success(f"Deleted supplier '{supplier.name}'. Please refresh the page.")

        # Live progress for all suppliers (table) and selected one (bar)
        with get_session() as session:
            all_suppliers = session.query(Supplier).order_by(Supplier.name).all()
        rows = []
        for s in all_suppliers:
            p = read_progress(f"scrape:{s.name}")
            status = p.get("status", "idle")
            if status == "error":
                status_label = "Failed"
            elif status == "skipped":
                status_label = "Skipped"
            elif status == "done":
                status_label = "Completed"
            elif status == "running":
                status_label = "Running"
            else:
                status_label = "Idle"
            rows.append({
                "Supplier": s.name,
                "Status": status_label,
                "Progress %": p.get("pct", 0.0),
                "Scraped": p.get("scraped", 0),
                "Stored": p.get("stored", 0),
            })
        grid_col, bar_col = st.columns([2, 1])
        with grid_col:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        with bar_col:
            if supplier_rows:
                prog = read_progress(f"scrape:{supplier_rows[0]['name']}")
                st.progress(min(max(float(prog.get("pct", 0.0)) / 100.0, 0.0), 1.0), text=f"{supplier_rows[0]['name']}: {prog.get('pct', 0)}%")
                st.metric("Stored", value=prog.get("stored", 0), delta=None)

    if run_all:
        def _bg_run():
            with get_session() as session:
                write_progress("scrape:all", {"pct": 0.0, "scraped": 0, "stored": 0, "status": "running"})
                run_all_scrapers(session, progress_key="scrape:all", batch_size=500)
        threading.Thread(target=_bg_run, daemon=True).start()
        st.success("Scraping started in background. Progress will update live.")

with tab_bom:
    st.subheader("Upload & Process BOM")
    st.write("Accepted: CSV, Excel (.xlsx). Columns: Part_Name, Description, Quantity, Package, Voltage, Other_Specs")
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

    with get_session() as session:
        total_parts = session.query(Part).count()
    if total_parts == 0:
        st.warning("No supplier data found. Please run scrapers or upload a custom list first.")

    if uploaded_file is not None:
        try:
            bom_df = read_bom_file(uploaded_file)
            bom_df = normalize_bom_columns(bom_df)
        except Exception as exc:
            st.error(f"Failed to read BOM file: {exc}")
            st.stop()

        ok, missing = validate_bom_columns(bom_df.columns)
        if not ok:
            st.warning(f"Missing expected columns: {', '.join(missing)}")

        st.write("Preview (first 100 rows):")
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
            available_df = results_df[results_df["Status"] == "Available"].copy()
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

            st.subheader("❌ Unavailable in Store")
            unavailable_df = results_df[results_df["Status"] == "Unavailable"].copy()
            if not unavailable_df.empty:
                st.dataframe(
                    unavailable_df[["BOM Part Name", "Similarity %", "Status"]],
                    use_container_width=True,
                )

            # Suggestions with add-to-available capability
            st.subheader("▼ Suggestions (Unique Alternatives)")
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
                # Add one of the suggestions to Available Matches
                with st.form("add_suggestion_form"):
                    st.caption("Add a suggested item to Available Matches")
                    sel_idx = st.selectbox(
                        "Choose suggestion",
                        options=list(range(len(suggestions_df))),
                        format_func=lambda i: f"{suggestions_df.iloc[i]['Found Part Name']} ({suggestions_df.iloc[i]['Supplier']})",
                    )
                    add_submit = st.form_submit_button("Add to Available")
                    if add_submit:
                        row = suggestions_df.iloc[int(sel_idx)].to_dict()
                        # Construct a new available row with minimal required fields
                        new_row = {
                            "Status": "Available",
                            "BOM Part Name": row.get("Found Part Name"),
                            "Found Part Name": row.get("Found Part Name"),
                            "Supplier": row.get("Supplier"),
                            "Price": row.get("Price"),
                            "Stock Availability": row.get("Stock Availability"),
                            "Image": row.get("Image"),
                            "Datasheet Link": row.get("Datasheet Link"),
                            "Purchase Link": row.get("Purchase Link"),
                            "Similarity %": row.get("Similarity %", 0.0),
                        }
                        results_df = pd.concat([results_df, pd.DataFrame([new_row])], ignore_index=True)
                        st.success("Suggestion added to Available Matches. Exports will include it.")
            else:
                st.caption("No alternative suggestions available.")

            csv_bytes = dataframe_to_download_bytes(results_df, kind="csv")
            xlsx_bytes = dataframe_to_download_bytes(results_df, kind="xlsx")
            from app.budget_excel import build_budget_excel
            budget_xlsx = build_budget_excel(bom_df=bom_df, results_df=results_df)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.download_button("⬇ Download CSV", data=csv_bytes, file_name="bom_results.csv", mime="text/csv")
            with col2:
                st.download_button("⬇ Download Excel", data=xlsx_bytes, file_name="bom_results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with col3:
                st.download_button("📊 Download Budget Excel", data=budget_xlsx, file_name="bom_budget.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab_inventory:
    st.subheader("Inventory by Supplier")
    with get_session() as session:
        inv_supplier_names = [s.name for s in session.query(Supplier).order_by(Supplier.name).all()]
    sel_inv = st.multiselect("Suppliers", options=inv_supplier_names, default=inv_supplier_names)
    page_size = st.number_input("Page size", min_value=25, max_value=1000, value=100, step=25)
    page_num = st.number_input("Page", min_value=1, value=1, step=1)

    def _primary_price(price_json: Optional[str]) -> Optional[str]:
        if not price_json:
            return None
        try:
            tiers = json.loads(price_json)
            if isinstance(tiers, list) and tiers:
                return tiers[0].get("price") or tiers[0].get("unit_price")
        except Exception:
            return None
        return None

    with get_session() as session:
        q = session.query(Part, Supplier.name.label("supplier_name")).join(Supplier)
        if sel_inv:
            q = q.filter(Supplier.name.in_(sel_inv))
        total = q.count()
        offset = (int(page_num) - 1) * int(page_size)
        rows_q = q.order_by(Part.id.desc()).offset(offset).limit(int(page_size)).all()

    items = []
    for part, sup_name in rows_q:
        items.append({
            "Supplier": sup_name,
            "Part Number": part.part_number,
            "Name": part.name,
            "Description": part.description,
            "Stock": part.stock,
            "Price": _primary_price(part.price_tiers_json),
            "Datasheet": part.datasheet_url,
            "Purchase": part.purchase_url,
            "Image": part.image_url,
        })
    st.caption(f"Total items: {total}")
    inv_df = pd.DataFrame(items)
    st.dataframe(
        inv_df,
        use_container_width=True,
        column_config={
            "Image": st.column_config.ImageColumn("Image", width="small"),
            "Datasheet": st.column_config.LinkColumn("Datasheet"),
            "Purchase": st.column_config.LinkColumn("Purchase"),
        },
    )
    if not inv_df.empty:
        st.download_button(
            "⬇ Download Current Page (CSV)",
            data=inv_df.to_csv(index=False).encode("utf-8"),
            file_name="inventory_page.csv",
            mime="text/csv",
        )

st.caption("Disclaimer: Prices and availability may change. Data is provided as-is.")