from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin
import time
import re

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
                category_selector="#navbar-ex1-collapse ul li ul.dropdown-menu li ul li a",  # relaxed selector
                pagination_selector="i.fa-angle-right",
                product_link_selector=".product-desc > a",
                name_selector="tr",
                code_selector="tr",
                price_selector="tr",
                description_selector=".panel-body div.panel-body",
                image_selector=".active img.img-responsive",
            )
        else:
            self.sitemap = sitemap

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        try:
            r = requests.get(url, headers=self.headers, timeout=25, allow_redirects=True)
            if r.status_code >= 400:
                return None
            return BeautifulSoup(r.text, "lxml")
        except Exception:
            return None

    def _abs(self, href: str | None) -> str | None:
        if not href:
            return None
        return urljoin(self.base_url, href)

    def _is_valid_product_link(self, url: Optional[str]) -> bool:
        if not url or "/product/" not in url:
            return False
        try:
            r = requests.get(url, headers=self.headers, timeout=15, allow_redirects=True)
            if r.status_code >= 400:
                return False
            return "/product/" in r.url
        except Exception:
            return False

    def _iter_pages(self, start_url: str):
        soup = self._get(start_url)
        if not soup:
            return
        yield soup
        while True:
            next_icon = soup.select_one(self.sitemap.pagination_selector)
            if not next_icon:
                break
            a = next_icon.find_parent("a")
            href = a.get("href") if a else next_icon.get("href")
            next_url = self._abs(href)
            if not next_url:
                break
            soup = self._get(next_url)
            if not soup:
                break
            yield soup
            time.sleep(0.2)

    def _extract_label_value(self, soup: BeautifulSoup, label: str) -> Optional[str]:
        # Find a table row where any cell contains the label (case-insensitive), then return the second td text
        for tr in soup.select("tr"):
            cells = tr.find_all(["td", "th"]) or []
            if not cells:
                continue
            row_text = " ".join(c.get_text(" ", strip=True) for c in cells).lower()
            if label.lower() in row_text and len(cells) >= 2:
                # Try to get the second td specifically
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    val = tds[1].get_text(" ", strip=True)
                    if val:
                        return val
                # Fallback to second cell
                val = cells[1].get_text(" ", strip=True)
                if val:
                    return val
        return None

    def _parse_product_page(self, url: str) -> Optional[SupplierResult]:
        if not self._is_valid_product_link(url):
            return None
        soup = self._get(url)
        if not soup:
            return None
        name = self._extract_label_value(soup, "Name")
        code = self._extract_label_value(soup, "Code")
        price = self._extract_label_value(soup, "Price")
        # If neither name nor price was found, skip
        if not (name or price):
            return None
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

    def search(self, query: str, max_results: int = 80) -> List[SupplierResult]:
        search_url = f"https://tronic.lk/?s={requests.utils.quote(query)}&post_type=product"
        results: List[SupplierResult] = []
        for soup in self._iter_pages(search_url):
            for a in soup.select(self.sitemap.product_link_selector):
                href = self._abs(a.get("href"))
                if not self._is_valid_product_link(href):
                    continue
                res = self._parse_product_page(href)
                if res:
                    results.append(res)
                if len(results) >= max_results:
                    return results
        return results

    def crawl_all(self) -> List[SupplierResult]:
        # Crawl all products from All Products listing via pagination (no categories needed)
        start_url = "https://tronic.lk/shop/products"
        results: List[SupplierResult] = []
        for soup in self._iter_pages(start_url):
            for a in soup.select(self.sitemap.product_link_selector):
                href = self._abs(a.get("href"))
                if not self._is_valid_product_link(href):
                    continue
                res = self._parse_product_page(href)
                if res:
                    results.append(res)
        return results