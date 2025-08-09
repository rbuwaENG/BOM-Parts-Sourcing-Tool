from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Iterable, Tuple, List, Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from .db import get_session
from .models import Supplier, Part

REQUIRED_COLUMNS = [
    "Part_Name",
    "Description",
    "Quantity",
    "Package",
    "Voltage",
    "Other_Specs",
]


def read_bom_file(uploaded) -> pd.DataFrame:
    filename = uploaded.name.lower()
    if filename.endswith(".csv"):
        # Read raw bytes and try multiple encodings
        raw: bytes = uploaded.read()
        encodings_to_try = ["utf-8", "utf-8-sig", "cp1252", "latin1"]
        last_err = None
        for enc in encodings_to_try:
            try:
                text = raw.decode(enc, errors="strict")
                return pd.read_csv(io.StringIO(text))
            except Exception as exc:
                last_err = exc
                continue
        # Fallback: replace undecodable bytes to avoid hard failure
        text = raw.decode("utf-8", errors="replace")
        return pd.read_csv(io.StringIO(text))
    else:
        # Excel handler
        return pd.read_excel(uploaded)


def normalize_bom_columns(df: pd.DataFrame) -> pd.DataFrame:
    def norm(s: str) -> str:
        return "".join(ch for ch in s.lower() if ch.isalnum())

    alias_map: Dict[str, str] = {
        # Part name
        "partname": "Part_Name",
        "name": "Part_Name",
        "item": "Part_Name",
        "component": "Part_Name",
        # Description
        "description": "Description",
        "desc": "Description",
        # Quantity
        "qty": "Quantity",
        "quantity": "Quantity",
        # Package / footprint
        "package": "Package",
        "footprint": "Package",
        # Voltage
        "voltage": "Voltage",
        "volt": "Voltage",
        # Other Specs
        "otherspecs": "Other_Specs",
        "specs": "Other_Specs",
        "parameters": "Other_Specs",
    }

    rename_map: Dict[str, str] = {}
    for col in df.columns:
        key = norm(str(col))
        if key in alias_map:
            rename_map[col] = alias_map[key]
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def validate_bom_columns(cols: Iterable[str]) -> Tuple[bool, List[str]]:
    cols_set = {c.strip() for c in cols}
    missing = [c for c in REQUIRED_COLUMNS if c not in cols_set]
    return (len(missing) == 0, missing)


def initialize_database_with_sample_data() -> None:
    # Seed minimal suppliers and parts if DB empty
    with get_session() as session:
        supplier_count = session.query(Supplier).count()
        part_count = session.query(Part).count()
        if supplier_count > 0 or part_count > 0:
            return

        # Add suppliers
        tronic = Supplier(name="Tronic.lk", base_url="https://tronic.lk")
        lcsc = Supplier(name="LCSC", base_url="https://www.lcsc.com")
        mouser = Supplier(name="Mouser", base_url="https://www.mouser.com")
        session.add_all([tronic, lcsc, mouser])
        session.flush()

        # Load sample parts
        samples_path = Path("data/sample_parts.csv")
        if samples_path.exists():
            df = pd.read_csv(samples_path)
            for _, r in df.iterrows():
                supplier_name = r.get("Supplier")
                supplier = session.query(Supplier).filter_by(name=supplier_name).first()
                if not supplier:
                    continue
                price_tiers = [{"qty": 1, "price": str(r.get("Price"))}]
                part = Part(
                    supplier_id=supplier.id,
                    part_number=r.get("Part_Number"),
                    name=r.get("Name"),
                    description=r.get("Description"),
                    package=r.get("Package"),
                    voltage=r.get("Voltage"),
                    other_specs=r.get("Other_Specs"),
                    stock=r.get("Stock"),
                    price_tiers_json=json.dumps(price_tiers),
                    datasheet_url=r.get("Datasheet"),
                    purchase_url=r.get("Purchase_Link"),
                    image_url=r.get("Image"),
                )
                session.add(part)
        session.commit()


def dataframe_to_download_bytes(df: pd.DataFrame, kind: str = "csv") -> bytes:
    if kind == "csv":
        return df.to_csv(index=False).encode("utf-8")
    elif kind == "xlsx":
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        buf.seek(0)
        return buf.read()
    else:
        raise ValueError("Unsupported kind")


# -------- Custom product list inference --------
_url_re = re.compile(r"^https?://", re.IGNORECASE)
_img_re = re.compile(r"\.(png|jpe?g|gif|webp|bmp)(\?.*)?$", re.IGNORECASE)
_pdf_re = re.compile(r"\.pdf(\?.*)?$", re.IGNORECASE)


def _norm_header(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _is_url(v: object) -> bool:
    if v is None:
        return False
    try:
        return bool(_url_re.match(str(v).strip()))
    except Exception:
        return False


def infer_custom_product_mapping(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    headers = list(df.columns)
    norm_map = {h: _norm_header(str(h)) for h in headers}

    def pick_by_keywords(keywords: List[str]) -> Optional[str]:
        for h in headers:
            nh = norm_map[h]
            if any(k in nh for k in keywords):
                return h
        return None

    # Heuristic picks
    name_col = pick_by_keywords(["name", "title", "product", "item", "component"]) or headers[0]
    desc_col = pick_by_keywords(["description", "desc", "details", "spec"])
    price_col = pick_by_keywords(["price", "cost", "unit", "amount", "rate"])
    stock_col = pick_by_keywords(["stock", "availability", "qty", "quantity", "available"])  # note: may be qty

    # URL-based detection
    url_counts = {h: int(df[h].apply(_is_url).sum()) for h in headers}

    # datasheet: prefer pdf urls or header indicates datasheet
    datasheet_col = pick_by_keywords(["datasheet", "datashett", "data", "sheet"]) or None
    if not datasheet_col:
        # choose any column with many urls and mostly pdf
        best = None
        best_pdf = 0
        for h in headers:
            if url_counts[h] == 0:
                continue
            pdf_hits = int(df[h].astype(str).str.contains(_pdf_re).sum())
            if pdf_hits > best_pdf:
                best_pdf = pdf_hits
                best = h
        datasheet_col = best

    # image: url column with image extension
    image_col = pick_by_keywords(["image", "img", "picture", "photo", "thumbnail"]) or None
    if not image_col:
        best = None
        best_img = 0
        for h in headers:
            if url_counts[h] == 0:
                continue
            img_hits = int(df[h].astype(str).str.contains(_img_re).sum())
            if img_hits > best_img:
                best_img = img_hits
                best = h
        image_col = best

    # purchase link: url column with many urls, not image/pdf
    purchase_col = pick_by_keywords(["link", "url", "href", "buy", "product"]) or None
    if not purchase_col:
        best = None
        best_count = 0
        for h in headers:
            if url_counts[h] == 0:
                continue
            non_asset = int(df[h].apply(lambda v: _is_url(v) and not _img_re.search(str(v)) and not _pdf_re.search(str(v))).sum())
            if non_asset > best_count:
                best_count = non_asset
                best = h
        purchase_col = best

    # part number: optional
    pn_col = pick_by_keywords(["mpn", "part", "sku", "code", "model"]) or None

    return {
        "part_number": pn_col,
        "name": name_col,
        "description": desc_col,
        "price": price_col,
        "stock": stock_col,
        "datasheet": datasheet_col,
        "purchase_link": purchase_col,
        "image": image_col,
    }


def normalize_custom_records(df: pd.DataFrame, mapping: Dict[str, Optional[str]]) -> List[Dict[str, Optional[str]]]:
    out: List[Dict[str, Optional[str]]] = []
    for _, r in df.iterrows():
        out.append({
            "part_number": str(r.get(mapping["part_number"])) if mapping.get("part_number") and pd.notna(r.get(mapping["part_number"])) else None,
            "name": str(r.get(mapping["name"])) if mapping.get("name") and pd.notna(r.get(mapping["name"])) else None,
            "description": str(r.get(mapping["description"])) if mapping.get("description") and pd.notna(r.get(mapping["description"])) else None,
            "price": str(r.get(mapping["price"])) if mapping.get("price") and pd.notna(r.get(mapping["price"])) else None,
            "stock": str(r.get(mapping["stock"])) if mapping.get("stock") and pd.notna(r.get(mapping["stock"])) else None,
            "datasheet": str(r.get(mapping["datasheet"])) if mapping.get("datasheet") and pd.notna(r.get(mapping["datasheet"])) else None,
            "purchase_link": str(r.get(mapping["purchase_link"])) if mapping.get("purchase_link") and pd.notna(r.get(mapping["purchase_link"])) else None,
            "image": str(r.get(mapping["image"])) if mapping.get("image") and pd.notna(r.get(mapping["image"])) else None,
        })
    return out


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return " ".join(str(value).lower().split())


def match_bom_to_parts_list(bom_df: pd.DataFrame, parts_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    from rapidfuzz import fuzz
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    # Prepare parts text corpus (Description + Name)
    parts_desc = parts_df.get("Description", pd.Series([""] * len(parts_df)))
    parts_name = parts_df.get("Name", pd.Series([""] * len(parts_df)))
    parts_text = (parts_desc.fillna("") + " " + parts_name.fillna("")).apply(_normalize_text)

    vectorizer = TfidfVectorizer(stop_words="english")
    parts_matrix = vectorizer.fit_transform(parts_text.tolist())

    matched_rows = []
    updated_bom_rows = []

    for _, b in bom_df.iterrows():
        bom_name = _normalize_text(b.get("Part_Name"))
        bom_specs = _normalize_text(b.get("Description")) + " " + _normalize_text(b.get("Package")) + " " + _normalize_text(b.get("Voltage")) + " " + _normalize_text(b.get("Other_Specs"))
        bom_vec = vectorizer.transform([bom_specs])
        tfidf_scores = cosine_similarity(bom_vec, parts_matrix).ravel() * 100.0  # 0-100

        # Fuzzy name ratio
        name_scores = parts_name.fillna("").apply(lambda x: float(fuzz.ratio(bom_name, _normalize_text(x))))

        total_scores = 0.8 * tfidf_scores + 0.2 * name_scores.values
        best_idx = int(total_scores.argmax()) if len(total_scores) else -1

        if best_idx >= 0:
            pr = parts_df.iloc[best_idx]
            # Build matched parts table row (Updated Parts List format)
            matched_rows.append({
                "Category": pr.get("Category"),
                "Category-href": pr.get("Category-href"),
                "Name": pr.get("Name"),
                "Code": pr.get("Code"),
                "Price": pr.get("Price"),
                "Description": pr.get("Description"),
                "Img": pr.get("Img"),
                "_similarity": round(float(total_scores[best_idx]), 1),
            })
            # Build updated BOM row (original BOM fields + matched fields)
            updated_row = b.to_dict()
            updated_row.update({
                "Matched_Category": pr.get("Category"),
                "Matched_Category_href": pr.get("Category-href"),
                "Matched_Name": pr.get("Name"),
                "Matched_Code": pr.get("Code"),
                "Matched_Price": pr.get("Price"),
                "Matched_Description": pr.get("Description"),
                "Matched_Img": pr.get("Img"),
                "Matched_Similarity": round(float(total_scores[best_idx]), 1),
            })
            updated_bom_rows.append(updated_row)
        else:
            # No parts; keep BOM with NaNs on matched fields
            updated_row = b.to_dict()
            updated_row.update({
                "Matched_Category": None,
                "Matched_Category_href": None,
                "Matched_Name": None,
                "Matched_Code": None,
                "Matched_Price": None,
                "Matched_Description": None,
                "Matched_Img": None,
                "Matched_Similarity": 0.0,
            })
            updated_bom_rows.append(updated_row)

    matched_df = pd.DataFrame(matched_rows)
    # Return only the specified columns for matched table (drop similarity helper)
    if not matched_df.empty and "_similarity" in matched_df.columns:
        matched_df = matched_df.drop(columns=["_similarity"])
    updated_bom_df = pd.DataFrame(updated_bom_rows)
    return matched_df, updated_bom_df