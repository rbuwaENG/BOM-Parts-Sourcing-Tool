from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Iterable, Tuple, List, Dict

import pandas as pd
from sqlalchemy.orm import Session

from .db import get_session
from .models import Supplier, Part

REQUIRED_COLUMNS = [
    "Part_Number",
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
        # Part number
        "partnumber": "Part_Number",
        "mpn": "Part_Number",
        "partno": "Part_Number",
        "mfrpart": "Part_Number",
        "manufacturerpartnumber": "Part_Number",
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