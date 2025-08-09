import json
import time
from typing import Optional
from datetime import datetime

import pandas as pd
import bootstrap  # noqa: F401
import streamlit as st
from sqlalchemy.orm import Session

from app.db import get_session, ensure_db_initialized
from app.models import Supplier, SupplierRule, Part
from app.scrapers.troniclk import TronicLkScraper, TronicSitemap
from app.scheduler import write_progress, read_progress, set_last_update_time

st.set_page_config(page_title="Supplier Edit", layout="wide")
st.title("Supplier Management")
# Ensure DB and tables exist
ensure_db_initialized()

# Load suppliers as plain dicts to avoid detached instance errors
with get_session() as session:
    suppliers = session.query(Supplier).order_by(Supplier.name).all()
    supplier_rows = [{"id": s.id, "name": s.name, "is_active": s.is_active} for s in suppliers]

supplier_names = [s["name"] for s in supplier_rows]
sel_name = st.selectbox("Select supplier", options=supplier_names)
if not sel_name:
    st.stop()

selected = next(s for s in supplier_rows if s["name"] == sel_name)
with get_session() as session:
    supplier = session.get(Supplier, selected["id"])
    rule = session.query(SupplierRule).filter_by(supplier_id=supplier.id).first()

st.subheader(f"Edit: {supplier.name}")
col1, col2 = st.columns(2)
with col1:
    is_active = st.toggle("Supplier active", value=bool(supplier.is_active))
with col2:
    rule_enabled = st.toggle("Scraper enabled", value=bool(rule.is_enabled) if rule else True)

st.markdown("Sitemap JSON (used by scraper):")
initial_json = rule.sitemap_json if rule and rule.sitemap_json else ""
new_json = st.text_area("Sitemap JSON", value=initial_json, height=220, placeholder="Paste JSON here")

save = st.button("Save Settings")
if save:
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

st.divider()
st.subheader("Run Scraper")
run_now = st.button("Run Now (Background)")

progress_key = f"scrape:{supplier.name}"
progress = read_progress(progress_key)
prog_col, stats_col = st.columns([2, 3])
with prog_col:
    pct = float(progress.get("pct", 0.0))
    st.progress(min(max(pct / 100.0, 0.0), 1.0), text=f"Progress: {pct:.1f}%")
with stats_col:
    st.json({
        "scraped": progress.get("scraped", 0),
        "stored": progress.get("stored", 0),
        "status": progress.get("status", "idle"),
    })

preview = st.checkbox("Show latest scraped preview", value=True)
page_size = st.number_input("Preview page size", min_value=10, max_value=200, value=30, step=10)

if run_now:
    # Run scraper in foreground for demo (would be background threaded/async normally)
    with get_session() as session:
        rule = session.query(SupplierRule).filter_by(supplier_id=supplier.id).first()
        sitemap = None
        if rule and rule.sitemap_json:
            try:
                data = json.loads(rule.sitemap_json)
                selectors = {s['id']: s for s in data.get('selectors', [])}
                sitemap = TronicSitemap(
                    category_selector=selectors['category']['selector'],
                    pagination_selector=selectors['pagination']['selector'],
                    product_link_selector=selectors['product_link']['selector'],
                    name_selector=selectors['name']['selector'],
                    code_selector=selectors['code']['selector'],
                    price_selector=selectors['price']['selector'],
                    description_selector=selectors['description']['selector'],
                    image_selector=selectors['image']['selector'],
                )
            except Exception:
                sitemap = None
        scraper = TronicLkScraper(sitemap=sitemap)

        write_progress(progress_key, {"pct": 0.0, "scraped": 0, "stored": 0, "status": "running"})
        results = scraper.crawl_all()
        scraped = 0
        stored = 0
        total = max(len(results), 1)
        for res in results:
            scraped += 1
            # Store into DB (upsert naïve approach)
            sup = session.query(Supplier).filter_by(name=res.supplier).first()
            if not sup:
                continue
            part = Part(
                supplier_id=sup.id,
                part_number=res.found_part_number,
                name=res.name,
                description=res.description,
                package=None,
                voltage=None,
                other_specs=None,
                stock=res.stock,
                price_tiers_json=json.dumps([{ "qty": 1, "price": res.price or "" }]),
                datasheet_url=res.datasheet_link,
                purchase_url=res.purchase_link,
                image_url=res.image_url,
            )
            session.add(part)
            stored += 1
            if scraped % 10 == 0 or scraped == total:
                session.commit()
                write_progress(progress_key, {
                    "pct": min(100.0, scraped * 100.0 / total),
                    "scraped": scraped,
                    "stored": stored,
                    "status": "running",
                })
        session.commit()
        set_last_update_time(datetime.utcnow())
        write_progress(progress_key, {"pct": 100.0, "scraped": scraped, "stored": stored, "status": "done"})
    st.success(f"Scraper finished. Stored {stored} items.")

if preview:
    with get_session() as session:
        parts = session.query(Part).filter(Part.supplier_id == supplier.id).order_by(Part.id.desc()).limit(1000).all()
    rows = []
    for p in parts:
        rows.append({
            "Found Part Name": p.name or p.part_number,
            "Supplier": supplier.name,
            "Price": None,
            "Stock Availability": p.stock,
            "Image": p.image_url,
            "Datasheet Link": p.datasheet_url,
            "Purchase Link": p.purchase_url,
        })
    df = pd.DataFrame(rows)
    tabs = st.tabs(["Page 1", "Page 2", "Page 3"])
    per_tab = max(1, int(page_size))
    for i, tab in enumerate(tabs):
        with tab:
            start = i * per_tab
            end = start + per_tab
            st.dataframe(
                df.iloc[start:end],
                use_container_width=True,
                column_config={
                    "Image": st.column_config.ImageColumn("Image", width="small"),
                    "Datasheet Link": st.column_config.LinkColumn("Datasheet Link"),
                    "Purchase Link": st.column_config.LinkColumn("Purchase Link"),
                },
            )