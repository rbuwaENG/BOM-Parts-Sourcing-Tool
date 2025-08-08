from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class SupplierResult:
    supplier: str
    found_part_number: Optional[str]
    name: Optional[str]
    description: Optional[str]
    price: Optional[str]
    stock: Optional[str]
    datasheet_link: Optional[str]
    purchase_link: Optional[str]
    image_url: Optional[str]
    extra: Dict[str, Any]


class SupplierScraper:
    supplier_name: str

    def search(self, query: str, max_results: int = 20) -> List[SupplierResult]:
        raise NotImplementedError

    def fetch_by_part_number(self, part_number: str) -> List[SupplierResult]:
        # Default behavior: perform a search with the part number
        return self.search(part_number, max_results=10)