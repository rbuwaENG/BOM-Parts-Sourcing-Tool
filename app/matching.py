from __future__ import annotations

from typing import Dict, List, Tuple, Any, Optional

import pandas as pd
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from .models import Part, Supplier


class BomRow:
    def __init__(
        self,
        part_number: Optional[str],
        description: Optional[str],
        quantity: Optional[int],
        package: Optional[str],
        voltage: Optional[str],
        other_specs: Optional[str],
    ) -> None:
        self.part_number = part_number
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


def compute_weighted_similarity(bom: BomRow, part: Part) -> float:
    part_num_sim = 0.0
    if bom.part_number and part.part_number:
        pn_a = _normalize_text(bom.part_number)
        pn_b = _normalize_text(part.part_number)
        if pn_a and pn_b:
            part_num_sim = _levenshtein_similarity(pn_a, pn_b)

    def join_specs(desc, pkg, volt, other):
        return " ".join([_normalize_text(x) for x in [desc, pkg, volt, other] if x])

    bom_specs = join_specs(bom.description, bom.package, bom.voltage, bom.other_specs)
    part_specs = join_specs(part.description, part.package, part.voltage, part.other_specs)

    spec_sim = _tfidf_cosine_similarity(bom_specs, part_specs)

    if bom.part_number and part.part_number:
        combined = 0.5 * part_num_sim + 0.5 * spec_sim
    else:
        combined = spec_sim

    return max(0.0, min(100.0, combined))


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
        pn = row.get("Part_Number")
        pn = str(pn).strip() if pd.notna(pn) else None
        pn = pn if pn else None
        bom = BomRow(
            part_number=pn,
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

        candidates = [p for p in parts if stock_ok(p)]
        scored: List[Tuple[Part, float]] = []
        for p in candidates:
            score = compute_weighted_similarity(bom, p)
            scored.append((p, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        best = scored[0] if scored else (None, 0.0)
        if best[0] is not None and best[1] >= min_similarity:
            part = best[0]
            supplier_name = session.get(Supplier, part.supplier_id).name
            results.append({
                "BOM Part Name": bom.description or bom.part_number,
                "Found Part Name": part.name or part.part_number,
                "Supplier": supplier_name,
                "Price": _extract_primary_price(part.price_tiers_json),
                "Stock Availability": part.stock,
                "Image": part.image_url,
                "Datasheet Link": part.datasheet_url,
                "Purchase Link": part.purchase_url,
                "Similarity %": round(best[1], 1),
            })
        else:
            results.append({
                "BOM Part Name": bom.description or bom.part_number,
                "Found Part Name": None,
                "Supplier": None,
                "Price": None,
                "Stock Availability": None,
                "Image": None,
                "Datasheet Link": None,
                "Purchase Link": None,
                "Similarity %": round(best[1], 1) if best[0] is not None else 0.0,
            })
            alt = []
            for p, s in scored[:20]:
                supplier_name = session.get(Supplier, p.supplier_id).name
                alt.append({
                    "found_part_name": p.name or p.part_number,
                    "supplier": supplier_name,
                    "price": _extract_primary_price(p.price_tiers_json),
                    "stock": p.stock,
                    "image": p.image_url,
                    "datasheet_link": p.datasheet_url,
                    "purchase_link": p.purchase_url,
                    "similarity": round(s, 1),
                })
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