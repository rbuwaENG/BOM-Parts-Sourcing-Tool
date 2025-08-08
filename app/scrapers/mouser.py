from __future__ import annotations

from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from .base import SupplierScraper, SupplierResult


class MouserScraper(SupplierScraper):
    supplier_name = "Mouser"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.base_url = "https://www.mouser.com/"

    def _build_search_url(self, query: str) -> str:
        from requests.utils import quote
        return f"https://www.mouser.com/c/?q={quote(query)}"

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
            items = soup.select(".search-results-products tr, .SearchResultsRow, .row")
            results = []
            for item in items[:max_results]:
                name_el = item.select_one("a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                link = self._abs(name_el.get("href"))
                price_el = item.select_one(".price, .Price, .price-breaks")
                price = price_el.get_text(strip=True) if price_el else None
                stock_el = item.select_one(".availability, .Availability")
                stock = stock_el.get_text(strip=True) if stock_el else None
                img_el = item.select_one("img")
                img_url = self._abs(img_el.get("data-src") or img_el.get("src")) if img_el else None
                results.append(
                    SupplierResult(
                        supplier=self.supplier_name,
                        found_part_number=None,
                        name=name,
                        description=None,
                        price=price,
                        stock=stock,
                        datasheet_link=None,
                        purchase_link=link,
                        image_url=img_url,
                        extra={},
                    )
                )
            return results
        except Exception:
            return []