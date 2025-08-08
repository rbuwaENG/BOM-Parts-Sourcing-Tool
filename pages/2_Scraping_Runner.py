import json
import time
import pandas as pd
import bootstrap  # noqa: F401
import streamlit as st

from datetime import datetime
from app.db import get_session
from app.models import Supplier, SupplierRule, Part
from app.scheduler import read_progress, write_progress, set_last_update_time
from app.scrapers.troniclk import TronicLkScraper, TronicSitemap

st.set_page_config(page_title="Scraping Runner", layout="wide")
st.title("Scraping Runner & Monitor")

run_all = st.button("Run All Scrapers Now")

if run_all:
    with get_session() as session:
        suppliers = session.query(Supplier).order_by(Supplier.name).all()
        for s in suppliers:
            rule = session.query(SupplierRule).filter_by(supplier_id=s.id).first()
            if rule and rule.is_enabled is False:
                continue
            key = f"scrape:{s.name}"
            write_progress(key, {"pct": 0.0, "scraped": 0, "stored": 0, "status": "running"})
            if s.name == "Tronic.lk":
                sitemap = None
                if rule and rule.sitemap_json:
                    try:
                        data = json.loads(rule.sitemap_json)
                        selectors = {sel['id']: sel for sel in data.get('selectors', [])}
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
                results = scraper.crawl_all()
                scraped = 0
                stored = 0
                total = max(len(results), 1)
                for r in results:
                    scraped += 1
                    part = Part(
                        supplier_id=s.id,
                        part_number=r.found_part_number,
                        name=r.name,
                        description=r.description,
                        stock=r.stock,
                        price_tiers_json=json.dumps([{ "qty": 1, "price": r.price or "" }]),
                        datasheet_url=r.datasheet_link,
                        purchase_url=r.purchase_link,
                        image_url=r.image_url,
                    )
                    session.add(part)
                    if scraped % 10 == 0:
                        session.commit()
                    stored += 1
                    if scraped % 20 == 0 or scraped == total:
                        write_progress(key, {"pct": min(100.0, scraped*100.0/total), "scraped": scraped, "stored": stored, "status": "running"})
                session.commit()
                write_progress(key, {"pct": 100.0, "scraped": scraped, "stored": stored, "status": "done"})
            else:
                # Placeholder for other suppliers
                write_progress(key, {"pct": 100.0, "scraped": 0, "stored": 0, "status": "skipped"})
        set_last_update_time(datetime.utcnow())
    st.success("Scrapers completed.")

# Show live progress for all suppliers
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

st.info("Run scrapers first to populate the database, then go back to Home to process BOMs.")