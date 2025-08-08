from __future__ import annotations

from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from .base import SupplierScraper, SupplierResult


class LscsScraper(SupplierScraper):
    supplier_name = "LCSC"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.base_url = "https://www.lcsc.com/"

    def _build_search_url(self, query: str) -> str:
        from requests.utils import quote
        return f"https://www.lcsc.com/search?q={quote(query)}"

    def _abs(self, href: str | None) -> str | None:
        if not href:
            return None
        return urljoin(self.base_url, href)

    def search(self, query: str, max_results: int = 20):
        url = self._build_search_url(query)
        try:
            resp = requests.get(url, headers=self.headers, timeout=20)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "lxml")
            items = soup.select("div.product-item, div.product, li.product")
            results = []
            for item in items[:max_results]:
                name_el = item.select_one("a, h3, h2")
                name = name_el.get_text(strip=True) if name_el else None
                link = self._abs(name_el["href"]) if name_el and name_el.has_attr("href") else None
                price_el = item.select_one(".price, span.price, .product-price")
                price = price_el.get_text(strip=True) if price_el else None
                img_el = item.select_one("img")
                img_url = self._abs(img_el.get("data-src") or img_el.get("src")) if img_el else None

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
                        image_url=img_url,
                        extra={},
                    )
                )
            return results
        except Exception:
            return []