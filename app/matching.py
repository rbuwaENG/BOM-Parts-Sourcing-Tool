from __future__ import annotations

from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from .models import Part, Supplier, SupplierRule


class BomRow:
    def __init__(
        self,
        part_name: Optional[str],
        description: Optional[str],
        quantity: Optional[int],
        package: Optional[str],
        voltage: Optional[str],
        other_specs: Optional[str],
    ) -> None:
        self.part_name = part_name
        self.description = description
        self.quantity = quantity
        self.package = package
        self.voltage = voltage
        self.other_specs = other_specs


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).lower().split())


def _levenshtein_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(fuzz.ratio(a, b))


def _tfidf_cosine_similarity(text_a: str, text_b: str) -> float:
    if not text_a and not text_b:
        return 0.0
    vect = TfidfVectorizer(stop_words="english")
    mat = vect.fit_transform([text_a, text_b])
    sim = cosine_similarity(mat[0:1], mat[1:2]).ravel()[0]
    return float(sim * 100.0)


def compute_name_similarity(bom: BomRow, part: Part) -> float:
    a = _normalize_text(bom.part_name)
    b = _normalize_text(part.name)
    return _levenshtein_similarity(a, b)


def _purchase_link_or_fallback(session: Session, part: Part, default_query: Optional[str]) -> Optional[str]:
    if part.purchase_url:
        return part.purchase_url
    supplier = session.get(Supplier, part.supplier_id)
    # Try rule search template
    rule = session.query(SupplierRule).filter_by(supplier_id=part.supplier_id).first()
    if rule and rule.search_url_template and default_query:
        from requests.utils import quote
        return rule.search_url_template.replace("{query}", quote(default_query))
    # Fallback to supplier base_url
    return supplier.base_url if supplier and supplier.base_url else None


def find_best_matches_for_bom(
    session: Session,
    bom_df: pd.DataFrame,
    min_similarity: int = 70,
    in_stock_only: bool = False,
    supplier_filter: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, Dict[int, List[Dict[str, Any]]]]:
    query = session.query(Part).join(Supplier)
    if supplier_filter:
        query = query.filter(Supplier.name.in_(supplier_filter))
    parts: List[Part] = query.all()

    results: List[Dict[str, Any]] = []
    suggestions_map: Dict[int, List[Dict[str, Any]]] = {}

    for idx, row in bom_df.iterrows():
        name = row.get("Part_Name")
        name = str(name).strip() if pd.notna(name) else None
        bom = BomRow(
            part_name=name,
            description=str(row.get("Description")).strip() if pd.notna(row.get("Description")) else None,
            quantity=int(row.get("Quantity")) if pd.notna(row.get("Quantity")) else None,
            package=str(row.get("Package")).strip() if pd.notna(row.get("Package")) else None,
            voltage=str(row.get("Voltage")).strip() if pd.notna(row.get("Voltage")) else None,
            other_specs=str(row.get("Other_Specs")).strip() if pd.notna(row.get("Other_Specs")) else None,
        )

        def stock_ok(p: Part) -> bool:
            if not in_stock_only:
                return True
            if not p.stock:
                return False
            return any(s in p.stock.lower() for s in ["in stock", "available", "+", ">", "stock:"])

        candidates = [p for p in parts if stock_ok(p) and p.name]

        scored: List[Tuple[Part, float]] = []
        if bom.part_name:
            for p in candidates:
                score = compute_name_similarity(bom, p)
                if score > 0:
                    spec_sim = _tfidf_cosine_similarity(
                        _normalize_text(bom.description),
                        _normalize_text(p.description),
                    )
                    total = 0.9 * score + 0.1 * spec_sim
                    scored.append((p, total))
        else:
            scored = []

        scored.sort(key=lambda x: x[1], reverse=True)

        best = scored[0] if scored else (None, 0.0)
        if best[0] is not None and best[1] >= min_similarity:
            part = best[0]
            supplier_name = session.get(Supplier, part.supplier_id).name
            results.append({
                "Status": "Available",
                "BOM Part Name": bom.part_name,
                "Found Part Name": part.name,
                "Supplier": supplier_name,
                "Price": _extract_primary_price(part.price_tiers_json),
                "Stock Availability": part.stock,
                "Image": part.image_url,
                "Datasheet Link": part.datasheet_url,
                "Purchase Link": _purchase_link_or_fallback(session, part, default_query=part.name or bom.part_name),
                "Similarity %": round(best[1], 1),
            })
        else:
            results.append({
                "Status": "Unavailable",
                "BOM Part Name": bom.part_name,
                "Found Part Name": None,
                "Supplier": None,
                "Price": None,
                "Stock Availability": None,
                "Image": None,
                "Datasheet Link": None,
                "Purchase Link": None,
                "Similarity %": round(best[1], 1) if best[0] is not None else 0.0,
            })

        # Suggestions: top 20 unique by name+supplier+link
        alt = []
        seen = set()
        for p, s in scored[:50]:
            sup = session.get(Supplier, p.supplier_id).name
            link = _purchase_link_or_fallback(session, p, default_query=p.name)
            key = (sup, p.name, link)
            if key in seen:
                continue
            seen.add(key)
            alt.append({
                "found_part_name": p.name,
                "supplier": sup,
                "price": _extract_primary_price(p.price_tiers_json),
                "stock": p.stock,
                "image": p.image_url,
                "datasheet_link": p.datasheet_url,
                "purchase_link": link,
                "similarity": round(float(s), 1),
            })
            if len(alt) >= 20:
                break
        if alt:
            suggestions_map[idx] = alt

    df = pd.DataFrame(results)
    return df, suggestions_map


def _extract_primary_price(price_json: Optional[str]) -> Optional[str]:
    if not price_json:
        return None
    try:
        import json
        tiers = json.loads(price_json)
        if isinstance(tiers, list) and tiers:
            return tiers[0].get("price") or tiers[0].get("unit_price") or None
    except Exception:
        return None
    return None