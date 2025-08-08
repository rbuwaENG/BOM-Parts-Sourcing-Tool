from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin
import time

import requests
from bs4 import BeautifulSoup

from .base import SupplierScraper, SupplierResult


@dataclass
class TronicSitemap:
    category_selector: str
    pagination_selector: str
    product_link_selector: str
    name_selector: str
    code_selector: str
    price_selector: str
    description_selector: str
    image_selector: str


class TronicLkScraper(SupplierScraper):
    supplier_name = "Tronic.lk"

    def __init__(self, sitemap: Optional[TronicSitemap] = None):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        }
        self.base_url = "https://tronic.lk/"
        if sitemap is None:
            # Default to provided sitemap
            self.sitemap = TronicSitemap(
                category_selector="#navbar-ex1-collapse ul >  li:nth-child(4) ul.dropdown-menu li ul li a:not(:contains('All Products'))",
                pagination_selector="i.fa-angle-right",
                product_link_selector=".product-desc > a",
                name_selector="tr:contains('Name') td:nth-of-type(2)",
                code_selector="tr:contains('Code') td:nth-of-type(2)",
                price_selector="tr:contains('Price') td:nth-of-type(2)",
                description_selector=".panel-body div.panel-body",
                image_selector=".active img.img-responsive",
            )
        else:
            self.sitemap = sitemap

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        try:
            r = requests.get(url, headers=self.headers, timeout=25)
            if r.status_code != 200:
                return None
            return BeautifulSoup(r.text, "lxml")
        except Exception:
            return None

    def _abs(self, href: str | None) -> str | None:
        if not href:
            return None
        return urljoin(self.base_url, href)

    def _iter_category_pages(self, start_url: str):
        # Visit category, then follow pagination using selector
        soup = self._get(start_url)
        if not soup:
            return
        # gather product links on first page
        yield soup
        # follow pagination by clicking the angle-right until none
        while True:
            next_el = soup.select_one(self.sitemap.pagination_selector)
            if not next_el:
                break
            # The icon is within a link; move to its parent anchor if present
            link = next_el.parent.get("href") if next_el.parent and next_el.parent.name == "a" else next_el.get("href")
            next_url = self._abs(link)
            if not next_url:
                break
            soup = self._get(next_url)
            if not soup:
                break
            yield soup
            time.sleep(0.2)

    def _parse_product_page(self, url: str) -> Optional[SupplierResult]:
        soup = self._get(url)
        if not soup:
            return None
        # validate that this is a product page with required fields
        name_el = soup.select_one(self.sitemap.name_selector)
        code_el = soup.select_one(self.sitemap.code_selector)
        price_el = soup.select_one(self.sitemap.price_selector)
        # If essential fields missing, treat as invalid and skip
        if not (name_el or price_el):
            return None
        name = name_el.get_text(strip=True) if name_el else None
        code = code_el.get_text(strip=True) if code_el else None
        price = price_el.get_text(strip=True) if price_el else None
        desc_nodes = soup.select(self.sitemap.description_selector)
        description = " \n".join([n.get_text(" ", strip=True) for n in desc_nodes]) if desc_nodes else None
        img_el = soup.select_one(self.sitemap.image_selector)
        img_url = self._abs(img_el.get("src") if img_el else None)
        return SupplierResult(
            supplier=self.supplier_name,
            found_part_number=code,
            name=name,
            description=description,
            price=price,
            stock=None,
            datasheet_link=None,
            purchase_link=url,
            image_url=img_url,
            extra={"code": code},
        )

    def search(self, query: str, max_results: int = 40) -> List[SupplierResult]:
        # For query search, fallback to site search page behavior
        search_url = f"https://tronic.lk/?s={requests.utils.quote(query)}&post_type=product"
        soup = self._get(search_url)
        if not soup:
            return []
        results = []
        for a in soup.select(self.sitemap.product_link_selector)[:max_results * 2]:
            href = self._abs(a.get("href"))
            if not href or "/product/" not in href:
                continue
            res = self._parse_product_page(href)
            if res:
                results.append(res)
            if len(results) >= max_results:
                break
        return results

    def crawl_all(self) -> List[SupplierResult]:
        # Crawl categories and pagination using sitemap
        start_url = "https://tronic.lk/shop/products"
        root = self._get(start_url)
        if not root:
            return []
        category_links = [self._abs(a.get("href")) for a in root.select(self.sitemap.category_selector)]
        results: List[SupplierResult] = []
        for cat in category_links:
            if not cat:
                continue
            for soup in self._iter_category_pages(cat):
                for a in soup.select(self.sitemap.product_link_selector):
                    href = self._abs(a.get("href"))
                    if not href or "/product/" not in href:
                        continue
                    res = self._parse_product_page(href)
                    if res:
                        results.append(res)
        return results