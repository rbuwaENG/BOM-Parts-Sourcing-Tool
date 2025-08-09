from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Iterable, Set
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

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

    def __init__(self, sitemap: Optional[TronicSitemap] = None, max_workers: int = 8):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.base_url = "https://tronic.lk/"
        self.max_workers = max_workers
        if sitemap is None:
            self.sitemap = TronicSitemap(
                category_selector="#navbar-ex1-collapse a[href*='/category/'], #navbar-ex1-collapse a[href*='/product-category/']",
                pagination_selector=".pagination a, .page-numbers a, a[rel=next], li.pagination-next a, i.fa-angle-right",
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

    def _normalize_page_url(self, url: str, page_num: int) -> str:
        # Try standard WooCommerce paged format using /page/N/
        if "/page/" in url:
            base = url.split("/page/")[0].rstrip("/")
            return f"{base}/page/{page_num}/"
        # Fallback to query param paged
        parsed = urlparse(url)
        qs = dict(parse_qsl(parsed.query))
        qs["paged"] = str(page_num)
        new_query = urlencode(qs)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    def _collect_all_page_urls(self, soup: BeautifulSoup, first_url: str) -> List[str]:
        # Find numeric pagination links and compute max page
        pages = set()
        for a in soup.select(self.sitemap.pagination_selector):
            txt = (a.get_text(" ", strip=True) or "").strip()
            if txt.isdigit():
                pages.add(int(txt))
        max_page = max(pages) if pages else 1
        return [self._normalize_page_url(first_url, p) for p in range(1, max_page + 1)]

    def _collect_product_links_from_page(self, url: str) -> List[str]:
        soup = self._get(url)
        if not soup:
            return []
        links = [self._abs(a.get("href")) for a in soup.select(self.sitemap.product_link_selector)]
        return [l for l in links if self._is_valid_product_link(l)]

    def _get_all_category_links(self) -> List[str]:
        # Try to get categories from navigation menu
        soup = self._get(self.base_url)
        if not soup:
            return []
        cats = [self._abs(a.get("href")) for a in soup.select(self.sitemap.category_selector)]
        # Deduplicate and keep only category-like paths
        out = []
        seen = set()
        for c in cats:
            if not c:
                continue
            if "/category/" in c or "/product-category/" in c:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out

    def crawl_all(self) -> List[SupplierResult]:
        # Strategy: crawl all category pages and all their pagination, deduplicate product links, then fetch concurrently
        category_links = self._get_all_category_links()
        # Fallback to a products listing page if categories not found
        if not category_links:
            candidate = self._find_listing_start()
            if candidate:
                category_links = [candidate]
        if not category_links:
            return []

        product_links: Set[str] = set()
        for cat in category_links:
            soup = self._get(cat)
            if not soup:
                continue
            page_urls = self._collect_all_page_urls(soup, cat)
            for pu in page_urls:
                for l in self._collect_product_links_from_page(pu):
                    product_links.add(l)

        results: List[SupplierResult] = []
        if not product_links:
            return results

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._parse_product_page, url): url for url in product_links}
            for f in as_completed(futures):
                try:
                    r = f.result()
                    if r:
                        results.append(r)
                except Exception:
                    continue
        return results

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
        # Iterate over computed numeric pages if available
        page_urls = self._collect_all_page_urls(soup, start_url)
        for pu in page_urls[1:]:
            s2 = self._get(pu)
            if not s2:
                continue
            yield s2
            time.sleep(0.1)

    def search(self, query: str, max_results: int = 200) -> List[SupplierResult]:
        search_url = f"https://tronic.lk/?s={requests.utils.quote(query)}&post_type=product"
        results: List[SupplierResult] = []
        product_links: Set[str] = set()
        for soup in self._iter_pages(search_url):
            for a in soup.select(self.sitemap.product_link_selector):
                href = self._abs(a.get("href"))
                if self._is_valid_product_link(href):
                    product_links.add(href)
                if len(product_links) >= max_results:
                    break
            if len(product_links) >= max_results:
                break
        if not product_links:
            return []
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._parse_product_page, url): url for url in list(product_links)[:max_results]}
            for f in as_completed(futures):
                try:
                    r = f.result()
                    if r:
                        results.append(r)
                except Exception:
                    continue
        return results