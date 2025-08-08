from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Iterable
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
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.base_url = "https://tronic.lk/"
        if sitemap is None:
            self.sitemap = TronicSitemap(
                category_selector="#navbar-ex1-collapse ul li ul.dropdown-menu li ul li a",
                pagination_selector="a[rel=next], li.pagination-next a, i.fa-angle-right",
                product_link_selector="a[href*='/product/']",
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
        return bool(url and "/product/" in url)

    def _extract_label_value(self, soup: BeautifulSoup, label: str) -> Optional[str]:
        for tr in soup.select("tr"):
            cells = tr.find_all(["td", "th"]) or []
            if not cells:
                continue
            row_text = " ".join(c.get_text(" ", strip=True) for c in cells).lower()
            if label.lower() in row_text and len(cells) >= 2:
                tds = tr.find_all("td")
                if len(tds) >= 2:
                    val = tds[1].get_text(" ", strip=True)
                    if val:
                        return val
                val = cells[1].get_text(" ", strip=True)
                if val:
                    return val
        return None

    def _parse_product_page(self, url: str) -> Optional[SupplierResult]:
        soup = self._get(url)
        if not soup:
            return None
        name = self._extract_label_value(soup, "Name")
        code = self._extract_label_value(soup, "Code")
        price = self._extract_label_value(soup, "Price")
        if not (name or price):
            return None
        desc_nodes = soup.select(self.sitemap.description_selector)
        description = " \n".join([n.get_text(" ", strip=True) for n in desc_nodes]) if desc_nodes else None
        img_el = soup.select_one(self.sitemap.image_selector) or soup.select_one(".images img, .woocommerce-product-gallery__image img, img")
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

    def _find_listing_start(self) -> Optional[str]:
        candidates = [
            "https://tronic.lk/shop/products",
            "https://tronic.lk/products",
            "https://tronic.lk/?post_type=product&s=",
        ]
        for u in candidates:
            soup = self._get(u)
            if not soup:
                continue
            links = [self._abs(a.get("href")) for a in soup.select(self.sitemap.product_link_selector)]
            links = [l for l in links if self._is_valid_product_link(l)]
            if links:
                return u
        return None

    def _iter_pages(self, start_url: str) -> Iterable[BeautifulSoup]:
        soup = self._get(start_url)
        if not soup:
            return
        yield soup
        while True:
            next_link = None
            # try several pagination patterns
            for sel in ["a[rel=next]", "li.pagination-next a", "i.fa-angle-right"]:
                el = soup.select_one(sel)
                if el:
                    a = el if el.name == "a" else el.find_parent("a")
                    href = a.get("href") if a else el.get("href")
                    next_link = self._abs(href)
                    break
            if not next_link:
                break
            soup = self._get(next_link)
            if not soup:
                break
            yield soup
            time.sleep(0.2)

    def search(self, query: str, max_results: int = 100) -> List[SupplierResult]:
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
        start_url = self._find_listing_start()
        if not start_url:
            return []
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