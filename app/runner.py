from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from .models import Supplier, SupplierRule, Part
from .scheduler import write_progress, set_last_update_time
from .scrapers.troniclk import TronicLkScraper, TronicSitemap


def _build_tronic_scraper(rule: Optional[SupplierRule]) -> TronicLkScraper:
    sitemap = None
    if rule and rule.sitemap_json:
        try:
            data = json.loads(rule.sitemap_json)
            selectors = {sel['id']: sel for sel in data.get('selectors', [])}
            sitemap = TronicSitemap(
                category_selector=selectors.get('category', {}).get('selector', "#navbar-ex1-collapse a[href*='/category/'], #navbar-ex1-collapse a[href*='/product-category/']"),
                pagination_selector=selectors.get('pagination', {}).get('selector', ".pagination a, .page-numbers a, a[rel=next], li.pagination-next a, i.fa-angle-right"),
                product_link_selector=selectors.get('product_link', {}).get('selector', "a[href*='/product/']"),
                name_selector=selectors.get('name', {}).get('selector', 'tr'),
                code_selector=selectors.get('code', {}).get('selector', 'tr'),
                price_selector=selectors.get('price', {}).get('selector', 'tr'),
                description_selector=selectors.get('description', {}).get('selector', '.panel-body div.panel-body'),
                image_selector=selectors.get('image', {}).get('selector', '.active img.img-responsive'),
            )
        except Exception:
            sitemap = None
    return TronicLkScraper(sitemap=sitemap, max_workers=16)


def run_all_scrapers(session: Session, progress_key: str, batch_size: int = 250) -> None:
    suppliers: List[Supplier] = session.query(Supplier).order_by(Supplier.name).all()

    for s in suppliers:
        rule: Optional[SupplierRule] = session.query(SupplierRule).filter_by(supplier_id=s.id).first()
        if rule and rule.is_enabled is False:
            continue
        key = f"scrape:{s.name}"
        write_progress(key, {"pct": 0.0, "scraped": 0, "stored": 0, "status": "running"})

        if s.name == "Tronic.lk":
            scraper = _build_tronic_scraper(rule)
            results = scraper.crawl_all()
            scraped = 0
            stored = 0
            to_insert: List[Part] = []
            total = max(len(results), 1)
            for r in results:
                scraped += 1
                p = Part(
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
                to_insert.append(p)
                if len(to_insert) >= batch_size:
                    session.bulk_save_objects(to_insert, return_defaults=False)
                    session.commit()
                    stored += len(to_insert)
                    to_insert.clear()
                    write_progress(key, {"pct": min(100.0, scraped*100.0/total), "scraped": scraped, "stored": stored, "status": "running"})
            if to_insert:
                session.bulk_save_objects(to_insert, return_defaults=False)
                session.commit()
                stored += len(to_insert)
            write_progress(key, {"pct": 100.0, "scraped": scraped, "stored": stored, "status": "done"})
        else:
            write_progress(key, {"pct": 100.0, "scraped": 0, "stored": 0, "status": "skipped"})

    set_last_update_time(datetime.utcnow())