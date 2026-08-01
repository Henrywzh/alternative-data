"""Parsers for Hong Kong SRPE first-hand sales PDFs.

SRPE exposes the authoritative first-hand sales documents as PDFs rather than
as a public row-level data feed.  This module keeps the PDF-specific work
separate from the document catalogue in :mod:`srpe` so that parsing can be
tested against extracted tables without downloading the whole market.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import pdfplumber


TRANSACTION_COLUMNS = [
    "source_agency",
    "document_category",
    "development_id",
    "development_name",
    "phase_name",
    "development_address",
    "document_id",
    "document_serial_no",
    "document_hash",
    "source_document",
    "source_page",
    "date_of_pasp",
    "date_of_asp",
    "date_of_asp_termination",
    "block_name",
    "floor",
    "unit",
    "car_parking_space",
    "transaction_price_hkd",
    "price_revision_details",
    "payment_terms",
    "related_party_flag",
    "is_cancelled",
    "transaction_id",
]

PRICE_LIST_COLUMNS = [
    "source_agency",
    "document_category",
    "development_id",
    "development_name",
    "phase_name",
    "development_address",
    "document_id",
    "document_serial_no",
    "document_hash",
    "source_document",
    "source_page",
    "date_of_printing",
    "price_list_number",
    "price_list_series_key",
    "price_list_version_key",
    "is_revision",
    "total_residential_properties",
    "block_name",
    "floor",
    "unit",
    "saleable_area_sqm",
    "saleable_area_sqft",
    "price_hkd",
    "unit_rate_hkd_per_sqm",
    "unit_rate_hkd_per_sqft",
    "unit_key",
]

SIGNAL_COLUMNS = [
    "development_id",
    "development_name",
    "phase_name",
    "period",
    "sales_units_gross",
    "sales_value_gross_hkd",
    "cancelled_units",
    "cumulative_gross_units",
    "cumulative_cancelled_units",
    "cumulative_event_net_units",
    "cumulative_unique_active_units",
    "cumulative_net_units",
    "total_residential_properties",
    "cumulative_net_sell_through_pct",
    "median_transaction_price_hkd",
    "weighted_avg_transaction_price_hkd",
    "days_since_first_pasp",
]


def _read_pdf_bytes(source: bytes | bytearray | Path | str | Any) -> bytes:
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if hasattr(source, "read"):
        content = source.read()
        if isinstance(content, str):
            return content.encode("utf-8")
        return bytes(content)
    raise TypeError("source must be PDF bytes, a path, or a binary file-like object")


def sha256_pdf(source: bytes | bytearray | Path | str | Any) -> str:
    """Return the full content hash used to identify a PDF version."""
    return hashlib.sha256(_read_pdf_bytes(source)).hexdigest()


def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[ \t\r\f\v]+", " ", str(value).replace("\u00a0", " ")).strip()


def _clean_multiline(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _label_text(value: Any) -> str:
    """Flatten line breaks for matching bilingual PDF table headers."""
    return re.sub(r"\s+", " ", _clean_multiline(value)).strip()


def _prefer_english(value: Any) -> str:
    """Use the English line when a bilingual value has separate lines."""
    text = _clean_multiline(value)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    english_lines = [line for line in lines if re.search(r"[A-Za-z]{2,}", line)]
    if english_lines:
        return " ".join(english_lines)
    return _label_text(text)


def _row_cells(row: Sequence[Any], width: int) -> list[str]:
    cells = [_clean_multiline(cell) for cell in row]
    return cells[:width] + [""] * max(0, width - len(cells))


def _first_non_label_value(row: Sequence[Any], start: int) -> str:
    for value in row[start + 1 :]:
        candidate = _clean_multiline(value)
        if candidate:
            return candidate
    return ""


def _find_table_value(
    tables: Iterable[Sequence[Sequence[Any]]],
    label_fragments: Sequence[str],
) -> str:
    fragments = tuple(fragment.lower() for fragment in label_fragments)
    for table in tables:
        for row in table:
            for index, raw_cell in enumerate(row):
                cell = _clean(raw_cell).lower()
                if cell and any(fragment in cell for fragment in fragments):
                    value = _first_non_label_value(row, index)
                    if value:
                        return value
    return ""


def _parse_date(value: Any) -> str | None:
    text = _clean(value)
    if not text or text in {"-", "—", "NIL", "Nil"}:
        return None
    chinese = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if chinese:
        text = f"{chinese.group(1)}-{chinese.group(2)}-{chinese.group(3)}"
    else:
        match = re.search(r"\d{1,4}[/-]\d{1,2}[/-]\d{1,4}", text)
        if match:
            text = match.group(0)
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _parse_number(value: Any) -> float | None:
    text = _clean(value)
    if not text or text in {"-", "—", "NIL", "Nil"}:
        return None
    match = re.search(r"(?<!\d)(\d[\d,]*(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_area_pair(value: Any) -> tuple[float | None, float | None]:
    text = _clean_multiline(value)
    match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*\(\s*([\d,]+(?:\.\d+)?)\s*\)",
        text,
    )
    if not match:
        return None, None
    return (
        _parse_number(match.group(1)),
        _parse_number(match.group(2)),
    )


def _parse_rate_pair(value: Any) -> tuple[float | None, float | None]:
    return _parse_area_pair(value)


def _extract_basic_info(first_page_tables: Sequence[Sequence[Sequence[Any]]]) -> dict[str, Any]:
    development_name = _find_table_value(
        first_page_tables,
        ("name of development", "name of the phase"),
    )
    phase_name = _find_table_value(first_page_tables, ("phase no", "phase no."))
    development_address = _find_table_value(
        first_page_tables,
        ("location of development", "location of the phase"),
    )
    total = _find_table_value(
        first_page_tables,
        ("total number of residential properties",),
    )
    return {
        "development_name": _prefer_english(development_name),
        "phase_name": _prefer_english(phase_name),
        "development_address": _prefer_english(development_address),
        "total_residential_properties": _parse_number(total),
    }


def _transaction_table(table: Sequence[Sequence[Any]]) -> bool:
    text = " ".join(_label_text(cell) for row in table[:4] for cell in row)
    lowered = text.lower()
    return (
        ("date of pasp" in lowered or "臨時買賣" in text or "临时买卖" in text)
        and ("transaction price" in lowered or "成交金額" in text or "成交金额" in text)
    )


def parse_srpe_transaction_tables(
    page_tables: Iterable[tuple[int, Sequence[Sequence[Sequence[Any]]]]],
    *,
    metadata: Mapping[str, Any] | None = None,
    document_id: str | None = None,
    document_serial_no: str | None = None,
    document_hash: str | None = None,
    source_document: str | None = None,
) -> pd.DataFrame:
    """Parse extracted SRPE transaction tables into one row per unit event."""
    metadata = dict(metadata or {})
    records: list[dict[str, Any]] = []
    for page_no, tables in page_tables:
        for table in tables:
            if not _transaction_table(table):
                continue
            for row_no, raw_row in enumerate(table):
                row = _row_cells(raw_row, 11)
                pasp_date = _parse_date(row[0])
                asp_date = _parse_date(row[1])
                termination_date = _parse_date(row[2])
                price = _parse_number(row[7])
                property_present = any(row[index] for index in (3, 4, 5))
                if not (pasp_date or asp_date or termination_date):
                    continue
                if not property_present or price is None:
                    continue
                block = row[3]
                floor = row[4]
                unit = row[5]
                car_parking = row[6]
                stable_key = "|".join(
                    str(value or "")
                    for value in (
                        metadata.get("development_id"),
                        metadata.get("development_name"),
                        metadata.get("phase_name"),
                        pasp_date,
                        asp_date,
                        block,
                        floor,
                        unit,
                    )
                )
                records.append(
                    {
                        "source_agency": "SRPE",
                        "document_category": "register_of_transactions",
                        "development_id": metadata.get("development_id"),
                        "development_name": metadata.get("development_name"),
                        "phase_name": metadata.get("phase_name"),
                        "development_address": metadata.get("development_address"),
                        "document_id": document_id,
                        "document_serial_no": document_serial_no,
                        "document_hash": document_hash,
                        "source_document": source_document,
                        "source_page": page_no,
                        "date_of_pasp": pasp_date,
                        "date_of_asp": asp_date,
                        "date_of_asp_termination": termination_date,
                        "block_name": block,
                        "floor": floor,
                        "unit": unit,
                        "car_parking_space": car_parking,
                        "transaction_price_hkd": price,
                        "price_revision_details": row[8],
                        "payment_terms": row[9],
                        "related_party_flag": row[10],
                        "is_cancelled": bool(termination_date),
                        "transaction_id": hashlib.sha256(stable_key.encode("utf-8")).hexdigest(),
                        "_row_no": row_no,
                    }
                )
    result = pd.DataFrame(records)
    if result.empty:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)
    result = result.drop_duplicates(subset=["transaction_id"], keep="last")
    return result.drop(columns=["_row_no"], errors="ignore").reindex(columns=TRANSACTION_COLUMNS)


def parse_srpe_transaction_pdf(
    source: bytes | bytearray | Path | str | Any,
    *,
    development_id: str | None = None,
    development_name: str | None = None,
    phase_name: str | None = None,
    development_address: str | None = None,
    document_id: str | None = None,
    document_serial_no: str | None = None,
    source_document: str | None = None,
) -> pd.DataFrame:
    """Extract a SRPE register-of-transactions PDF."""
    content = _read_pdf_bytes(source)
    document_hash = hashlib.sha256(content).hexdigest()
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_tables = [(page_no, page.extract_tables() or []) for page_no, page in enumerate(pdf.pages, 1)]
    first_tables = page_tables[0][1] if page_tables else []
    extracted = _extract_basic_info(first_tables)
    metadata = {
        "development_id": development_id,
        "development_name": development_name or extracted.get("development_name"),
        "phase_name": phase_name or extracted.get("phase_name"),
        "development_address": development_address or extracted.get("development_address"),
    }
    return parse_srpe_transaction_tables(
        page_tables,
        metadata=metadata,
        document_id=document_id,
        document_serial_no=document_serial_no,
        document_hash=document_hash,
        source_document=source_document,
    )


def _price_table(table: Sequence[Sequence[Any]]) -> bool:
    text = " ".join(_label_text(cell) for row in table[:3] for cell in row).lower()
    return (
        (
            "block name" in text
            or "tower number" in text
            or "大廈名稱" in text
            or "大厦名称" in text
            or "座號" in text
            or "座号" in text
        )
        and ("saleable area" in text or "實用面積" in text or "实用面积" in text)
        and ("price" in text or "售價" in text or "售价" in text)
    )


def parse_srpe_price_list_metadata(
    first_page_tables: Sequence[Sequence[Sequence[Any]]],
    *,
    page_text: str = "",
) -> dict[str, Any]:
    """Extract the first-page identity and inventory fields from a price list."""
    info = _extract_basic_info(first_page_tables)
    printed_date = None
    price_list_number = None
    for table in first_page_tables:
        if not table:
            continue
        header = " ".join(_clean(cell) for cell in table[0]).lower()
        if "date of printing" not in header and "印製日期" not in header and "印制日期" not in header:
            continue
        if len(table) > 1:
            values = _row_cells(table[1], 2)
            printed_date = _parse_date(values[0])
            price_list_number = values[1] or None
        break
    if printed_date is None:
        match = re.search(
            r"(?:Date of Printing|印製日期|印制日期)\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{4}|[0-9]{1,2}\s+[A-Za-z]+\s+\d{4})",
            page_text,
            flags=re.IGNORECASE,
        )
        if match:
            printed_date = _parse_date(match.group(1))
    if price_list_number is None:
        match = re.search(r"(?:Number of Price List|價單編號|价单编号)\s*([0-9A-Za-z]+)", page_text, flags=re.IGNORECASE)
        if match:
            price_list_number = match.group(1)

    serial = str(price_list_number or "")
    return {
        **info,
        "date_of_printing": printed_date,
        "price_list_number": price_list_number,
        "is_revision": bool(re.search(r"[A-Za-z]", serial)),
    }


def _unit_key(block: str, floor: str, unit: str) -> str:
    return "|".join(re.sub(r"\s+", " ", value).strip().lower() for value in (block, floor, unit))


def parse_srpe_price_list_tables(
    page_tables: Iterable[tuple[int, Sequence[Sequence[Sequence[Any]]]]],
    *,
    metadata: Mapping[str, Any] | None = None,
    document_id: str | None = None,
    document_serial_no: str | None = None,
    document_hash: str | None = None,
    source_document: str | None = None,
) -> pd.DataFrame:
    """Parse price-list unit rows from extracted SRPE tables."""
    metadata = dict(metadata or {})
    series_key = "|".join(
        str(value or "")
        for value in (metadata.get("development_id"), metadata.get("development_name"), metadata.get("price_list_number"))
    )
    version_key = hashlib.sha256(
        "|".join((series_key, str(document_hash or ""))).encode("utf-8")
    ).hexdigest()
    records: list[dict[str, Any]] = []
    for page_no, tables in page_tables:
        for table in tables:
            if not _price_table(table):
                continue
            for raw_row in table:
                row = _row_cells(raw_row, 16)
                price = _parse_number(row[4])
                block, floor, unit = row[0], row[1], row[2]
                if price is None or not block or not unit:
                    continue
                area_sqm, area_sqft = _parse_area_pair(row[3])
                rate_sqm, rate_sqft = _parse_rate_pair(row[5])
                records.append(
                    {
                        "source_agency": "SRPE",
                        "document_category": "price_list",
                        "development_id": metadata.get("development_id"),
                        "development_name": metadata.get("development_name"),
                        "phase_name": metadata.get("phase_name"),
                        "development_address": metadata.get("development_address"),
                        "document_id": document_id,
                        "document_serial_no": document_serial_no,
                        "document_hash": document_hash,
                        "source_document": source_document,
                        "source_page": page_no,
                        "date_of_printing": metadata.get("date_of_printing"),
                        "price_list_number": metadata.get("price_list_number"),
                        "price_list_series_key": series_key,
                        "price_list_version_key": version_key,
                        "is_revision": metadata.get("is_revision", False),
                        "total_residential_properties": metadata.get("total_residential_properties"),
                        "block_name": block,
                        "floor": floor,
                        "unit": unit,
                        "saleable_area_sqm": area_sqm,
                        "saleable_area_sqft": area_sqft,
                        "price_hkd": price,
                        "unit_rate_hkd_per_sqm": rate_sqm,
                        "unit_rate_hkd_per_sqft": rate_sqft,
                        "unit_key": _unit_key(block, floor, unit),
                    }
                )
    if not records:
        return pd.DataFrame(columns=PRICE_LIST_COLUMNS)
    result = pd.DataFrame(records)
    return result.drop_duplicates(
        subset=["document_hash", "unit_key", "source_page", "price_hkd"],
        keep="last",
    ).reindex(columns=PRICE_LIST_COLUMNS)


def parse_srpe_price_list_pdf(
    source: bytes | bytearray | Path | str | Any,
    *,
    development_id: str | None = None,
    development_name: str | None = None,
    phase_name: str | None = None,
    development_address: str | None = None,
    document_id: str | None = None,
    document_serial_no: str | None = None,
    source_document: str | None = None,
) -> pd.DataFrame:
    """Extract unit prices and first-page metadata from an SRPE price list."""
    content = _read_pdf_bytes(source)
    document_hash = hashlib.sha256(content).hexdigest()
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page_tables = [(page_no, page.extract_tables() or []) for page_no, page in enumerate(pdf.pages, 1)]
        page_text = pdf.pages[0].extract_text() if pdf.pages else ""
    first_tables = page_tables[0][1] if page_tables else []
    extracted = parse_srpe_price_list_metadata(first_tables, page_text=page_text or "")
    metadata = {
        "development_id": development_id,
        "development_name": development_name or extracted.get("development_name"),
        "phase_name": phase_name or extracted.get("phase_name"),
        "development_address": development_address or extracted.get("development_address"),
        "date_of_printing": extracted.get("date_of_printing"),
        "price_list_number": extracted.get("price_list_number"),
        "is_revision": extracted.get("is_revision", False),
        "total_residential_properties": extracted.get("total_residential_properties"),
    }
    return parse_srpe_price_list_tables(
        page_tables,
        metadata=metadata,
        document_id=document_id,
        document_serial_no=document_serial_no,
        document_hash=document_hash,
        source_document=source_document,
    )


def build_srpe_sales_signals(
    transactions: pd.DataFrame,
    price_lists: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build project-month sales velocity, sell-through, price and cancellation signals."""
    if transactions is None or transactions.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)
    tx = transactions.copy()
    for column in ("date_of_pasp", "date_of_asp_termination"):
        tx[column] = pd.to_datetime(tx.get(column), errors="coerce")
    tx["transaction_price_hkd"] = pd.to_numeric(tx.get("transaction_price_hkd"), errors="coerce")
    if "is_cancelled" not in tx.columns:
        tx["is_cancelled"] = tx["date_of_asp_termination"].notna()
    key_columns = ["development_id", "development_name", "phase_name"]
    for column in key_columns:
        if column not in tx:
            tx[column] = None
    for column in ("block_name", "floor", "unit", "date_of_asp"):
        if column not in tx:
            tx[column] = ""
    if "transaction_id" not in tx:
        tx["transaction_id"] = tx.index.astype(str)
    tx["_unit_key"] = tx[["block_name", "floor", "unit"]].fillna("").astype(str).agg("|".join, axis=1)
    tx.loc[tx["_unit_key"].eq("||"), "_unit_key"] = tx.loc[tx["_unit_key"].eq("||"), "transaction_id"]
    tx["period"] = tx["date_of_pasp"].dt.to_period("M").dt.to_timestamp()
    tx = tx[tx["period"].notna()].copy()
    if tx.empty:
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    grouped = tx.groupby(key_columns + ["period"], dropna=False)
    result = grouped.agg(
        sales_units_gross=("transaction_id", "count"),
        sales_value_gross_hkd=("transaction_price_hkd", "sum"),
        median_transaction_price_hkd=("transaction_price_hkd", "median"),
    ).reset_index()
    weighted = (
        tx.assign(_weighted_price=tx["transaction_price_hkd"])
        .groupby(key_columns + ["period"], dropna=False)["_weighted_price"]
        .mean()
        .rename("weighted_avg_transaction_price_hkd")
        .reset_index()
    )
    result = result.merge(weighted, on=key_columns + ["period"], how="left")

    cancelled = tx[tx["date_of_asp_termination"].notna()].copy()
    if not cancelled.empty:
        cancelled["period"] = cancelled["date_of_asp_termination"].dt.to_period("M").dt.to_timestamp()
        cancellation_counts = (
            cancelled.groupby(key_columns + ["period"], dropna=False)
            .size()
            .rename("cancelled_units")
            .reset_index()
        )
        result = result.merge(cancellation_counts, on=key_columns + ["period"], how="outer")
    if "cancelled_units" not in result:
        result["cancelled_units"] = 0
    else:
        result["cancelled_units"] = result["cancelled_units"].fillna(0)
    for column in ("sales_units_gross", "sales_value_gross_hkd"):
        result[column] = result[column].fillna(0)
    result["sales_units_gross"] = result["sales_units_gross"].astype(int)
    result["cancelled_units"] = result["cancelled_units"].astype(int)
    result = result.sort_values(key_columns + ["period"]).reset_index(drop=True)
    result["cumulative_gross_units"] = result.groupby(key_columns, dropna=False)["sales_units_gross"].cumsum()
    result["cumulative_cancelled_units"] = result.groupby(key_columns, dropna=False)["cancelled_units"].cumsum()
    result["cumulative_event_net_units"] = result["cumulative_gross_units"] - result["cumulative_cancelled_units"]

    # The register can contain a preliminary agreement followed by its ASP,
    # or a later sale of the same unit.  For sell-through, count distinct unit
    # keys that have an active (non-terminated) record, rather than treating
    # every register row as a new unit.  The raw event counts remain visible
    # above for audit and contract-activity analysis.
    active = tx[~tx["is_cancelled"].astype(bool)].copy()
    if active.empty:
        result["cumulative_unique_active_units"] = 0
    else:
        active = active.sort_values(["_unit_key", "date_of_pasp", "date_of_asp"], na_position="last")
        first_active = active.drop_duplicates(subset=[*key_columns, "_unit_key"], keep="first").copy()
        first_active["period"] = first_active["date_of_pasp"].dt.to_period("M").dt.to_timestamp()
        unique_units = (
            first_active.groupby(key_columns + ["period"], dropna=False)
            .size()
            .rename("_unique_active_units")
            .reset_index()
        )
        result = result.merge(unique_units, on=key_columns + ["period"], how="left")
        result["_unique_active_units"] = result["_unique_active_units"].fillna(0).astype(int)
        result["cumulative_unique_active_units"] = result.groupby(key_columns, dropna=False)["_unique_active_units"].cumsum()
        result = result.drop(columns=["_unique_active_units"])
    result["cumulative_unique_active_units"] = result["cumulative_unique_active_units"].fillna(0).astype(int)
    result["cumulative_net_units"] = result["cumulative_unique_active_units"]

    if price_lists is not None and not price_lists.empty:
        project_key_columns = ["phase_name"]
        if (
            "development_id" in result.columns
            and "development_id" in price_lists.columns
            and result["development_id"].notna().any()
            and price_lists["development_id"].notna().any()
        ):
            project_key_columns.insert(0, "development_id")
        else:
            project_key_columns.insert(0, "development_name")
        inventory = (
            price_lists.groupby(project_key_columns, dropna=False)["total_residential_properties"]
            .max()
            .rename("total_residential_properties")
            .reset_index()
        )
        result = result.merge(inventory, on=project_key_columns, how="left")
    else:
        result["total_residential_properties"] = None
    result["cumulative_net_sell_through_pct"] = (
        result["cumulative_net_units"] / result["total_residential_properties"] * 100
    )
    first_dates = (
        tx.groupby(key_columns, dropna=False)["date_of_pasp"].min().rename("_first_pasp_date").reset_index()
    )
    result = result.merge(first_dates, on=key_columns, how="left")
    result["days_since_first_pasp"] = (result["period"] - result["_first_pasp_date"]).dt.days.clip(lower=0)
    result["period"] = result["period"].dt.strftime("%Y-%m-%d")
    return result.drop(columns=["_first_pasp_date"], errors="ignore").reindex(columns=SIGNAL_COLUMNS)
