from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from .base import SupplierScraper, SupplierResult


class TronicLkScraper(SupplierScraper):
    supplier_name = "Tronic.lk"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
        }

    def _build_search_url(self, query: str) -> str:
        from requests.utils import quote
        return f"https://tronic.lk/?s={quote(query)}&post_type=product"

    def search(self, query: str, max_results: int = 20):
        url = self._build_search_url(query)
        try:
            resp = requests.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            items = soup.select("ul.products li.product")
            results = []
            for item in items[:max_results]:
                name_el = item.select_one("h2.woocommerce-loop-product__title") or item.select_one("h2")
                name = name_el.get_text(strip=True) if name_el else None
                price_el = item.select_one("span.woocommerce-Price-amount") or item.select_one("span.price")
                price = price_el.get_text(strip=True) if price_el else None
                link_el = item.select_one("a.woocommerce-LoopProduct-link") or item.select_one("a")
                link = link_el["href"] if link_el and link_el.has_attr("href") else None

                results.append(
                    SupplierResult(
                        supplier=self.supplier_name,
                        found_part_number=None,
                        name=name,
                        description=None,
                        price=price,
                        stock=None,
                        datasheet_link=None,
                        purchase_link=link,
                        extra={},
                    )
                )
            return results
        except Exception:
            return []