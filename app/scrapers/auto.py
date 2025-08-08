from __future__ import annotations

import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from .base import SupplierScraper, SupplierResult


COMMON_CONTAINER_SELECTORS = [
    "ul.products li.product",
    "li.product",
    "div.product",
    "div.product-item",
    "div.card",
    "div.product-card",
    "div.item",
    "div.search-result",
    "tr",
]

COMMON_NAME_SELECTORS = [
    "h2",
    "h3",
    "a.product-title",
    "a.woocommerce-LoopProduct-link",
    "a",
]

COMMON_PRICE_SELECTORS = [
    "span.price",
    "span.woocommerce-Price-amount",
    "div.price",
    "span.amount",
    "p.price",
]

COMMON_STOCK_SELECTORS = [
    "span.stock",
    "div.stock",
    "p.stock",
]


def text_or_none(node) -> Optional[str]:
    if not node:
        return None
    text = node.get_text(strip=True)
    return text or None


class AutoDetectScraper(SupplierScraper):
    def __init__(self, supplier_name: str, search_url_template: Optional[str]):
        self.supplier_name = supplier_name
        self.search_url_template = search_url_template
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }

    def _build_search_url(self, query: str) -> Optional[str]:
        if not self.search_url_template:
            return None
        return self.search_url_template.replace("{query}", requests.utils.quote(query))

    def _detect_in_container(self, container) -> Optional[SupplierResult]:
        # Name
        name = None
        link = None
        for sel in COMMON_NAME_SELECTORS:
            el = container.select_one(sel)
            if el and text_or_none(el):
                name = text_or_none(el)
                if el.name == "a" and el.has_attr("href"):
                    link = el["href"]
                break

        # Price
        price = None
        for sel in COMMON_PRICE_SELECTORS:
            el = container.select_one(sel)
            if el and text_or_none(el):
                text = text_or_none(el)
                if text and re.search(r"(\$|€|£|Rs|USD|LKR).*?\d", text):
                    price = text
                    break

        # Stock
        stock = None
        for sel in COMMON_STOCK_SELECTORS:
            el = container.select_one(sel)
            if el and text_or_none(el):
                stock = text_or_none(el)
                break

        if not (name or price or stock or link):
            return None

        return SupplierResult(
            supplier=self.supplier_name,
            found_part_number=None,
            name=name,
            description=None,
            price=price,
            stock=stock,
            datasheet_link=None,
            purchase_link=link,
            extra={},
        )

    def search(self, query: str, max_results: int = 20) -> List[SupplierResult]:
        url = self._build_search_url(query)
        if not url:
            return []
        try:
            resp = requests.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            for cont_sel in COMMON_CONTAINER_SELECTORS:
                containers = soup.select(cont_sel)
                results = []
                for c in containers[: max_results * 2]:
                    r = self._detect_in_container(c)
                    if r:
                        results.append(r)
                    if len(results) >= max_results:
                        break
                if results:
                    return results
            return []
        except Exception:
            return []