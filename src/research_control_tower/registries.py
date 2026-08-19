"""Load and validate the Research Control Tower's versioned CSV registries.

All effective-date intervals use inclusive ``active_from`` and exclusive
``active_to`` semantics. A blank ``active_to`` is an open-ended interval.
The financial-data security crosswalk uses the sibling repository's stable-ID
algorithm: SHA-256 of ``"namespace\x1f" + canonical_ticker``.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from .contracts import RegistryBundle, ValidationIssue


REGISTRY_FILES = {
    "entities": "entities.csv",
    "listings": "listings.csv",
    "baskets": "baskets.csv",
    "basket_memberships": "basket_memberships.csv",
    "indices": "indices.csv",
}

REQUIRED_COLUMNS = {
    "entities": {
        "entity_id",
        "legal_name",
        "display_name",
        "country",
        "sector",
        "industry",
        "entity_type",
        "active_status",
        "active_from",
        "active_to",
        "registry_version",
    },
    "listings": {
        "listing_id",
        "entity_id",
        "exchange",
        "native_ticker",
        "canonical_ticker",
        "financial_data_security_id",
        "financial_data_issuer_group_id",
        "mapping_status",
        "mapping_verified_at",
        "mapping_source_url",
        "collection_eligible",
        "listing_role",
        "vendor_tickers",
        "currency",
        "primary_listing",
        "active_from",
        "active_to",
        "registry_version",
    },
    "baskets": {
        "basket_id",
        "display_name",
        "purpose",
        "active_from",
        "active_to",
        "registry_version",
    },
    "basket_memberships": {
        "entity_id",
        "basket_id",
        "membership_tier",
        "primary_layer",
        "secondary_layers",
        "active_from",
        "active_to",
        "membership_reason",
        "source_or_research_note",
        "registry_version",
    },
    "indices": {
        "index_id",
        "region",
        "display_name",
        "official_code",
        "official_code_namespace",
        "official_code_provider",
        "provider_symbol",
        "provider_symbol_namespace",
        "provider_symbol_provider",
        "provider",
        "active_from",
        "active_to",
        "registry_version",
    },
}

DATE_COLUMNS = {"active_from", "active_to", "mapping_verified_at"}
BOOLEAN_COLUMNS = {"primary_listing", "collection_eligible"}
MEMBERSHIP_TIERS = {"core", "read_through", "watch_only"}
ENTITY_TYPES = {"public", "private"}
MAPPING_STATUSES = {"verified", "unresolved"}
LISTING_ROLES = {"primary", "dual_primary", "secondary", "depositary_receipt"}
NEWS_ENTITY_ALIAS_FILENAME = "news_entity_aliases.csv"
NEWS_ALIAS_KINDS = {"positive", "negative"}
NEWS_ALIAS_MODES = {"word", "substring"}
AI_BASKET_ID = "AI_BOTTLENECKS_GLOBAL"
FOCUS_STAGE_1_BASKET_ID = "RESEARCH_STAGE_1_CHINA_INTERNET"
REQUIRED_BASKETS = {
    "US_VALUE",
    "US_GROWTH",
    "HK_VALUE",
    "HK_INTERNET",
    "HK_AI_THEMATIC",
    AI_BASKET_ID,
    FOCUS_STAGE_1_BASKET_ID,
}
REQUIRED_INDICES = {"CSI500", "STOXX_EUROPE_600"}
REQUIRED_AI_ANCHORS = {
    "NVIDIA", "AMD", "BROADCOM", "MARVELL", "CAMBRICON", "SK_HYNIX",
    "MICRON", "SAMSUNG_ELECTRONICS", "NANYA_TECHNOLOGY", "WINBOND", "TSMC",
    "SMIC", "HUA_HONG_SEMICONDUCTOR", "UMC", "GLOBALFOUNDRIES", "ASE_TECHNOLOGY",
    "AMKOR", "BESI", "HANMI_SEMICONDUCTOR", "JCET", "ASML", "APPLIED_MATERIALS",
    "LAM_RESEARCH", "KLA", "ASM_INTERNATIONAL", "NAURA", "UNIMICRON", "NAN_YA_PCB",
    "IBIDEN", "AJINOMOTO", "ARISTA_NETWORKS", "LUMENTUM", "COHERENT", "ACCTON",
    "ZTE", "QUANTA", "WISTRON", "WIWYNN", "DELL", "HPE", "VERTIV", "EATON",
    "MONOLITHIC_POWER_SYSTEMS", "DELTA_ELECTRONICS", "SCHNEIDER_ELECTRIC", "GE_VERNOVA",
    "CONSTELLATION_ENERGY", "VISTRA", "SIEMENS_ENERGY", "MICROSOFT", "AMAZON",
    "ALPHABET", "META", "ORACLE", "TENCENT", "ALIBABA",
}
SUPPORTED_ID = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")


def _blank(value: object) -> bool:
    if value is None or value is pd.NA:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _stable_id(namespace: str, *parts: object) -> str:
    identity = "\x1f".join([namespace, *(str(part) for part in parts)])
    return sha256(identity.encode("utf-8")).hexdigest()


def _parse_dates(frame: pd.DataFrame, registry_name: str) -> None:
    for column in sorted(DATE_COLUMNS.intersection(frame.columns)):
        raw = frame[column].astype("string").str.strip()
        parsed = pd.to_datetime(
            raw.where(raw.ne("")), format="%Y-%m-%d", errors="coerce"
        )
        invalid = raw.ne("") & parsed.isna()
        if invalid.any():
            row_index = int(invalid[invalid].index[0])
            value = raw.loc[row_index]
            raise ValueError(
                f"{registry_name} row {row_index} has invalid {column}: {value!r}"
            )
        frame[column] = parsed


def _parse_booleans(frame: pd.DataFrame, registry_name: str) -> None:
    for column in sorted(BOOLEAN_COLUMNS.intersection(frame.columns)):
        raw = frame[column].astype("string").str.strip().str.lower()
        parsed = raw.map({"true": True, "false": False, "1": True, "0": False})
        invalid = raw.ne("") & parsed.isna()
        if invalid.any():
            row_index = int(invalid[invalid].index[0])
            value = raw.loc[row_index]
            raise ValueError(
                f"{registry_name} row {row_index} has invalid {column}: {value!r}"
            )
        frame[column] = parsed.astype("boolean")


def _read_csv(path: Path, registry_name: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {registry_name} registry: {path}")

    frame = pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        skipinitialspace=False,
    )
    missing = sorted(REQUIRED_COLUMNS[registry_name] - set(frame.columns))
    if missing:
        raise ValueError(
            f"{registry_name} registry is missing required columns: {', '.join(missing)}"
        )

    for column in frame.select_dtypes(include=["string"]).columns:
        frame[column] = frame[column].str.strip()
    _parse_dates(frame, registry_name)
    _parse_booleans(frame, registry_name)
    return frame


def load_registry_bundle(config_root: Path) -> RegistryBundle:
    """Load all five CSV registries from ``config_root`` with stable dtypes."""

    root = Path(config_root)
    frames = {
        name: _read_csv(root / filename, name)
        for name, filename in REGISTRY_FILES.items()
    }
    return RegistryBundle(**frames)


def load_news_entity_aliases(path: Path) -> pd.DataFrame:
    """Load the versioned news entity alias/negative-exclusion table (Batch 5).

    The table is keyed by ``entity_id`` and carries ``alias_kind``
    (``positive`` matching token or ``negative`` exclusion token),
    ``match_token``, ``match_mode`` (``word`` boundary vs ``substring``) and a
    ``registry_version`` for versioning.  It is a small adjunct to the registry
    crosswalks -- not a standalone replacement alias dictionary.
    """

    frame = pd.read_csv(path, dtype="string", keep_default_na=False)
    required = {
        "entity_id",
        "alias_kind",
        "match_token",
        "match_mode",
        "registry_version",
        "source_or_research_note",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            f"news entity aliases are missing required columns: {', '.join(missing)}"
        )
    for column in frame.select_dtypes(include=["string"]).columns:
        frame[column] = frame[column].str.strip()
    invalid_kind = frame.loc[
        ~frame["alias_kind"].str.lower().isin(NEWS_ALIAS_KINDS), "alias_kind"
    ].unique()
    if len(invalid_kind):
        raise ValueError(
            f"news entity aliases have invalid alias_kind values: {sorted(invalid_kind)}"
        )
    invalid_mode = frame.loc[
        ~frame["match_mode"].str.lower().isin(NEWS_ALIAS_MODES), "match_mode"
    ].unique()
    if len(invalid_mode):
        raise ValueError(
            f"news entity aliases have invalid match_mode values: {sorted(invalid_mode)}"
        )
    blank = frame["entity_id"].map(_blank) | frame["match_token"].map(_blank)
    if blank.any():
        raise ValueError("news entity aliases must not have a blank entity_id or match_token")
    if frame["registry_version"].map(_blank).any():
        raise ValueError("news entity aliases must declare registry_version on every row")
    return frame


def _news_contains_word(haystack: str, token: str) -> bool:
    """Whole-token (word-boundary) containment match over a casefolded string."""

    if not token:
        return False
    if not any(char.isalnum() for char in token):
        return token in haystack
    start = 0
    while True:
        start = haystack.find(token, start)
        if start < 0:
            return False
        before_ok = start == 0 or not haystack[start - 1].isalnum()
        after = start + len(token)
        after_ok = after >= len(haystack) or not haystack[after].isalnum()
        if before_ok and after_ok:
            return True
        start += 1


def _verified_collection_listings(listings: pd.DataFrame) -> dict[str, str]:
    """Map listing_id -> entity_id for verified, collection-eligible listings."""

    if listings is None or listings.empty:
        return {}
    subset = listings[
        listings["mapping_status"].astype("string").str.lower().eq("verified")
        & listings["collection_eligible"].fillna(False).astype(bool)
    ]
    return {
        str(row["listing_id"]).strip(): str(row["entity_id"]).strip()
        for _, row in subset.iterrows()
        if str(row["listing_id"]).strip()
    }


def resolve_news_entities(
    text: str,
    *,
    entities: pd.DataFrame,
    listings: pd.DataFrame,
    aliases: pd.DataFrame | None = None,
) -> tuple[list[str], list[str]]:
    """Resolve news headline/title text to registry entities and their listings.

    Deterministic and pure (no I/O).  Positive matching is registry-backed:
    whole-word display/legal names from ``entities.csv`` plus any explicit
    positive alias rows.  Negative-exclusion alias rows suppress an entity even
    when its name token is present (e.g. "Tencent Music" must not resolve to
    TENCENT; "Alibaba Pictures" must not resolve to ALIBABA).  Unmatchable text
    yields empty ids -- never a guessed link.  The listing crosswalk comes from
    ``listings.csv`` (``financial_data_security_id`` / ``canonical_ticker`` /
    ``vendor_tickers`` are the canonical identity carried per listing).
    """

    haystack = str(text or "").casefold()
    matched: set[str] = set()
    if entities is not None and not entities.empty:
        for _, entity in entities.iterrows():
            entity_id = str(entity.get("entity_id") or "").strip()
            if not entity_id:
                continue
            for key in ("display_name", "legal_name"):
                token = str(entity.get(key) or "").strip()
                if token and _news_contains_word(haystack, token.casefold()):
                    matched.add(entity_id)
                    break
    blocked: set[str] = set()
    if aliases is not None and not aliases.empty:
        for _, row in aliases.iterrows():
            kind = str(row.get("alias_kind") or "").strip().lower()
            mode = str(row.get("match_mode") or "substring").strip().lower()
            token = str(row.get("match_token") or "").strip().casefold()
            entity_id = str(row.get("entity_id") or "").strip()
            if not token or not entity_id:
                continue
            hit = (
                _news_contains_word(haystack, token)
                if mode == "word"
                else token in haystack
            )
            if not hit:
                continue
            if kind == "negative":
                blocked.add(entity_id)
            elif kind == "positive":
                matched.add(entity_id)
    matched -= blocked
    entity_ids = sorted(matched)
    listing_entities = _verified_collection_listings(listings)
    listing_ids = sorted(
        str(listing_id)
        for listing_id, entity_id in listing_entities.items()
        if entity_id in matched
    )
    return entity_ids, listing_ids


def _issue(
    code: str,
    message: str,
    registry: str,
    row_index: int | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        registry=registry,
        row_index=row_index,
    )


def _duplicate_issues(
    frame: pd.DataFrame, registry: str, key: str
) -> Iterable[ValidationIssue]:
    if key not in frame.columns:
        return
    duplicate_rows = frame[frame.duplicated(key, keep=False)]
    for value in duplicate_rows[key].drop_duplicates().tolist():
        yield _issue(
            f"duplicate_{key}",
            f"{registry} contains duplicate {key}={value!r}",
            registry,
        )


def _identifier_issues(
    frame: pd.DataFrame, registry: str, key: str
) -> Iterable[ValidationIssue]:
    if key not in frame.columns:
        return
    for row_index, value in frame[key].items():
        if _blank(value) or not SUPPORTED_ID.fullmatch(str(value)):
            yield _issue(
                "invalid_stable_identifier",
                f"{registry} row {row_index} has invalid stable {key}={value!r}",
                registry,
                int(row_index),
            )


def _required_value_issues(
    frame: pd.DataFrame, registry: str, columns: Iterable[str]
) -> Iterable[ValidationIssue]:
    for column in columns:
        if column not in frame.columns:
            continue
        for row_index, value in frame[column].items():
            if _blank(value):
                yield _issue(
                    f"missing_{column}",
                    f"{registry} row {row_index} is missing required {column}",
                    registry,
                    int(row_index),
                )


def _reference_issues(
    frame: pd.DataFrame,
    column: str,
    allowed: set[object],
    registry: str,
    code: str,
) -> Iterable[ValidationIssue]:
    if column not in frame.columns:
        return
    for row_index, value in frame[column].items():
        if _blank(value) or value not in allowed:
            yield _issue(
                code,
                f"{registry} row {row_index} references unknown {column}={value!r}",
                registry,
                int(row_index),
            )


def _as_timestamp(value: object) -> pd.Timestamp | None:
    if _blank(value):
        return None
    parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _date_issues(frame: pd.DataFrame, registry: str) -> Iterable[ValidationIssue]:
    for column in sorted(DATE_COLUMNS.intersection(frame.columns)):
        for row_index, value in frame[column].items():
            if not _blank(value) and _as_timestamp(value) is None:
                yield _issue(
                    f"invalid_{column}_date",
                    f"{registry} row {row_index} has invalid {column}={value!r}",
                    registry,
                    int(row_index),
                )


def _date_order_issues(
    frame: pd.DataFrame, registry: str
) -> Iterable[ValidationIssue]:
    if not {"active_from", "active_to"} <= set(frame.columns):
        return
    for row_index, row in frame[["active_from", "active_to"]].iterrows():
        active_from = _as_timestamp(row["active_from"])
        active_to = _as_timestamp(row["active_to"])
        if active_from is not None and active_to is not None and active_to <= active_from:
            yield _issue(
                "active_to_not_after_active_from",
                f"{registry} row {row_index} must satisfy active_to > active_from",
                registry,
                int(row_index),
            )


def _intervals_overlap(
    left_from: object,
    left_to: object,
    right_from: object,
    right_to: object,
) -> bool:
    left_start = _as_timestamp(left_from)
    right_start = _as_timestamp(right_from)
    if left_start is None or right_start is None:
        return False
    left_end = _as_timestamp(left_to)
    right_end = _as_timestamp(right_to)
    return (left_end is None or right_start < left_end) and (
        right_end is None or left_start < right_end
    )


def _interval_contains(
    parent_from: object,
    parent_to: object,
    child_from: object,
    child_to: object,
) -> bool:
    parent_start = _as_timestamp(parent_from)
    child_start = _as_timestamp(child_from)
    if parent_start is None or child_start is None or child_start < parent_start:
        return False
    parent_end = _as_timestamp(parent_to)
    child_end = _as_timestamp(child_to)
    return parent_end is None or (child_end is not None and child_end <= parent_end)


def _membership_interval_issues(
    memberships: pd.DataFrame,
) -> Iterable[ValidationIssue]:
    natural_key = [
        "entity_id",
        "basket_id",
        "registry_version",
        "active_from",
        "active_to",
    ]
    duplicate_rows = memberships[memberships.duplicated(natural_key, keep=False)]
    for _, row in duplicate_rows.drop_duplicates(natural_key).iterrows():
        yield _issue(
            "duplicate_membership_natural_key",
            "basket_memberships repeats the same entity, basket, version, and interval",
            "basket_memberships",
        )

    for (entity_id, basket_id), group in memberships.groupby(
        ["entity_id", "basket_id"], dropna=False
    ):
        rows = list(group.iterrows())
        for position, (left_index, left) in enumerate(rows):
            for right_index, right in rows[position + 1 :]:
                if _intervals_overlap(
                    left["active_from"],
                    left["active_to"],
                    right["active_from"],
                    right["active_to"],
                ):
                    yield _issue(
                        "overlapping_membership_intervals",
                        f"membership intervals overlap for {entity_id!r}/{basket_id!r}",
                        "basket_memberships",
                        int(right_index),
                    )


def _listing_mapping_issues(listings: pd.DataFrame) -> Iterable[ValidationIssue]:
    for row_index, row in listings.iterrows():
        status = str(row["mapping_status"])
        eligible = row["collection_eligible"]
        eligible_bool = False if _blank(eligible) else bool(eligible)
        if status not in MAPPING_STATUSES:
            yield _issue(
                "invalid_mapping_status",
                f"listing row {row_index} has invalid mapping_status={status!r}",
                "listings",
                int(row_index),
            )
            continue

        if status == "verified":
            for column in (
                "canonical_ticker",
                "financial_data_security_id",
                "mapping_verified_at",
                "mapping_source_url",
            ):
                if _blank(row[column]):
                    yield _issue(
                        f"mapping_verified_missing_{column}",
                        f"verified listing row {row_index} is missing {column}",
                        "listings",
                        int(row_index),
                    )
            if not eligible_bool:
                yield _issue(
                    "mapping_gate_verified_not_collection_eligible",
                    f"verified listing row {row_index} must be collection eligible",
                    "listings",
                    int(row_index),
                )
            canonical = row["canonical_ticker"]
            security_id = row["financial_data_security_id"]
            if not _blank(canonical) and not _blank(security_id):
                expected = _stable_id("security", canonical)
                if security_id != expected:
                    yield _issue(
                        "mapping_security_id_crosswalk_mismatch",
                        f"listing row {row_index} has an incorrect financial-data security ID",
                        "listings",
                        int(row_index),
                    )
            source = str(row["mapping_source_url"]).strip()
            if source and _is_generic_mapping_source(source):
                yield _issue(
                    "mapping_source_not_row_specific",
                    f"verified listing row {row_index} uses a generic mapping source",
                    "listings",
                    int(row_index),
                )
        elif eligible_bool:
            yield _issue(
                "mapping_unresolved_collection_eligible",
                f"unresolved listing row {row_index} cannot be collection eligible",
                "listings",
                int(row_index),
            )
        elif any(
            not _blank(row[column])
            for column in (
                "canonical_ticker",
                "financial_data_security_id",
                "financial_data_issuer_group_id",
                "mapping_verified_at",
            )
        ):
            yield _issue(
                "mapping_unresolved_has_crosswalk_data",
                f"unresolved listing row {row_index} must not carry verified crosswalk data",
                "listings",
                int(row_index),
            )

        if (
            not _blank(row["canonical_ticker"])
            and _blank(row["financial_data_security_id"])
        ) or (
            _blank(row["canonical_ticker"])
            and not _blank(row["financial_data_security_id"])
        ):
            yield _issue(
                "mapping_gate_missing_crosswalk",
                f"listing row {row_index} must provide canonical ticker and security ID together",
                "listings",
                int(row_index),
            )


def _is_generic_mapping_source(source: str) -> bool:
    normalized = source.rstrip("/")
    return normalized in {
        "https://www.szse.cn/English/siteMarketData/siteMarketDatas",
        "https://global.krx.co.kr/contents/GLB/03/0303/030301/JHPGLB030301.jsp",
        "https://www.jpx.co.jp/english/equities/listed-companies",
        "https://www.deutsche-boerse.com/dbg-en/our-company/about-us",
        "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities?sc_lang=en",
    }


def _listing_role_issues(
    bundle: RegistryBundle,
) -> Iterable[ValidationIssue]:
    listings = bundle.listings
    for row_index, row in listings.iterrows():
        role = str(row["listing_role"])
        expected_primary = role in {"primary", "dual_primary"}
        if role not in LISTING_ROLES:
            yield _issue(
                "invalid_listing_role",
                f"listing row {row_index} has invalid listing_role={role!r}",
                "listings",
                int(row_index),
            )
        elif _blank(row["primary_listing"]):
            yield _issue(
                "missing_primary_listing",
                f"listing row {row_index} is missing primary_listing",
                "listings",
                int(row_index),
            )
        elif bool(row["primary_listing"]) != expected_primary:
            yield _issue(
                "primary_listing_role_mismatch",
                f"listing row {row_index} has inconsistent primary_listing/listing_role",
                "listings",
                int(row_index),
            )

    for entity_index, entity in bundle.entities.iterrows():
        entity_type = str(entity.get("entity_type", "public")).strip().lower()
        if entity_type not in ENTITY_TYPES:
            yield _issue(
                "invalid_entity_type",
                f"entity row {entity_index} has invalid entity_type={entity_type!r}",
                "entities",
                int(entity_index),
            )
        if str(entity["active_status"]) != "active":
            continue
        if entity_type == "private":
            continue
        entity_listings = listings[listings["entity_id"] == entity["entity_id"]]
        active_listings = entity_listings[
            entity_listings.apply(
                lambda row: _intervals_overlap(
                    entity["active_from"],
                    entity["active_to"],
                    row["active_from"],
                    row["active_to"],
                ),
                axis=1,
            )
        ]
        if active_listings.empty:
            yield _issue(
                "active_entity_missing_primary_listing",
                f"active entity {entity['entity_id']!r} has no active primary listing",
                "entities",
                int(entity_index),
            )
            continue
        primary = active_listings[
            active_listings["listing_role"].isin({"primary", "dual_primary"})
            & active_listings["primary_listing"].fillna(False).astype(bool)
        ]
        if primary.empty:
            yield _issue(
                "active_entity_missing_primary_listing",
                f"active entity {entity['entity_id']!r} has no active primary listing",
                "entities",
                int(entity_index),
            )
        if len(primary) > 1 and not primary["listing_role"].eq("dual_primary").all():
            yield _issue(
                "multiple_primary_listings_without_dual_primary",
                f"active entity {entity['entity_id']!r} has multiple non-dual primary listings",
                "entities",
                int(entity_index),
            )


def _membership_reference_interval_issues(
    bundle: RegistryBundle,
) -> Iterable[ValidationIssue]:
    entities = bundle.entities
    baskets = bundle.baskets
    listings = bundle.listings
    for row_index, membership in bundle.basket_memberships.iterrows():
        matching_entities = entities[
            entities["entity_id"] == membership["entity_id"]
        ]
        if not any(
            _interval_contains(
                row["active_from"],
                row["active_to"],
                membership["active_from"],
                membership["active_to"],
            )
            for _, row in matching_entities.iterrows()
        ):
            yield _issue(
                "membership_outside_entity_interval",
                f"membership row {row_index} is not contained by an entity interval",
                "basket_memberships",
                int(row_index),
            )

        matching_baskets = baskets[baskets["basket_id"] == membership["basket_id"]]
        if not any(
            _interval_contains(
                row["active_from"],
                row["active_to"],
                membership["active_from"],
                membership["active_to"],
            )
            for _, row in matching_baskets.iterrows()
        ):
            yield _issue(
                "membership_outside_basket_interval",
                f"membership row {row_index} is not contained by a basket interval",
                "basket_memberships",
                int(row_index),
            )

        entity_listings = listings[listings["entity_id"] == membership["entity_id"]]
        if entity_listings.empty:
            continue
        if not any(
            _intervals_overlap(
                listing["active_from"],
                listing["active_to"],
                membership["active_from"],
                membership["active_to"],
            )
            for _, listing in entity_listings.iterrows()
        ):
            yield _issue(
                "membership_entity_has_no_overlapping_listing",
                f"membership row {row_index} has no listing covering its interval",
                "basket_memberships",
                int(row_index),
            )


def _membership_gate_issues(
    bundle: RegistryBundle,
) -> Iterable[ValidationIssue]:
    listings = bundle.listings
    memberships = bundle.basket_memberships
    for row_index, membership in memberships.iterrows():
        entity_listings = listings[listings["entity_id"] == membership["entity_id"]]
        eligible = entity_listings[
            entity_listings["collection_eligible"].fillna(False).astype(bool)
        ]
        if (
            str(membership["membership_tier"]) != "watch_only"
            and eligible.empty
        ):
            yield _issue(
                "membership_requires_watch_only_without_eligible_listing",
                f"membership row {row_index} must be watch_only without an eligible listing",
                "basket_memberships",
                int(row_index),
            )

        if str(membership["basket_id"]) == AI_BASKET_ID and entity_listings.empty:
            yield _issue(
                "ai_member_without_listing",
                f"AI member row {row_index} does not resolve to a listing",
                "basket_memberships",
                int(row_index),
            )

        layer_tokens = {
            token.strip()
            for token in str(membership["secondary_layers"]).split(";")
            if token.strip()
        }
        if layer_tokens & set(bundle.baskets["basket_id"]):
            yield _issue(
                "secondary_layers_contains_basket_id",
                f"membership row {row_index} places a basket ID in secondary_layers",
                "basket_memberships",
                int(row_index),
            )


def validate_registry_bundle(bundle: RegistryBundle) -> list[ValidationIssue]:
    """Return deterministic validation issues without mutating ``bundle``."""

    issues: list[ValidationIssue] = []
    key_by_registry = {
        "entities": "entity_id",
        "listings": "listing_id",
        "baskets": "basket_id",
        "indices": "index_id",
    }
    for registry, key in key_by_registry.items():
        frame = getattr(bundle, registry)
        issues.extend(_duplicate_issues(frame, registry, key))
        issues.extend(_identifier_issues(frame, registry, key))
        issues.extend(
            _required_value_issues(frame, registry, {"registry_version", "active_from"})
        )
    issues.extend(
        _required_value_issues(
            bundle.basket_memberships,
            "basket_memberships",
            {"registry_version", "active_from"},
        )
    )

    entity_ids = set(bundle.entities.get("entity_id", pd.Series(dtype="string")).dropna())
    basket_ids = set(bundle.baskets.get("basket_id", pd.Series(dtype="string")).dropna())
    issues.extend(
        _reference_issues(
            bundle.listings,
            "entity_id",
            entity_ids,
            "listings",
            "orphan_listing_entity_id",
        )
    )
    issues.extend(
        _reference_issues(
            bundle.basket_memberships,
            "entity_id",
            entity_ids,
            "basket_memberships",
            "orphan_membership_entity_id",
        )
    )
    issues.extend(
        _reference_issues(
            bundle.basket_memberships,
            "basket_id",
            basket_ids,
            "basket_memberships",
            "orphan_membership_basket_id",
        )
    )

    for registry in REGISTRY_FILES:
        frame = getattr(bundle, registry if registry != "basket_memberships" else "basket_memberships")
        issues.extend(_date_issues(frame, registry))
        issues.extend(_date_order_issues(frame, registry))

    issues.extend(_listing_mapping_issues(bundle.listings))
    issues.extend(_listing_role_issues(bundle))
    issues.extend(_membership_interval_issues(bundle.basket_memberships))
    issues.extend(_membership_reference_interval_issues(bundle))
    issues.extend(_membership_gate_issues(bundle))

    if "membership_tier" in bundle.basket_memberships.columns:
        for row_index, value in bundle.basket_memberships["membership_tier"].items():
            if value not in MEMBERSHIP_TIERS:
                issues.append(
                    _issue(
                        "invalid_membership_tier",
                        f"basket_memberships row {row_index} has invalid membership_tier={value!r}",
                        "basket_memberships",
                        int(row_index),
                    )
                )

    if {"basket_id", "membership_tier", "primary_layer"} <= set(
        bundle.basket_memberships.columns
    ):
        ai_core = bundle.basket_memberships[
            (bundle.basket_memberships["basket_id"] == AI_BASKET_ID)
            & (bundle.basket_memberships["membership_tier"] == "core")
        ]
        for row_index, value in ai_core["primary_layer"].items():
            if _blank(value):
                issues.append(
                    _issue(
                        "ai_core_missing_primary_layer",
                        f"AI core membership row {row_index} must declare primary_layer",
                        "basket_memberships",
                        int(row_index),
                    )
                )

    actual_baskets = set(bundle.baskets.get("basket_id", pd.Series(dtype="string")))
    for basket_id in sorted(REQUIRED_BASKETS - actual_baskets):
        issues.append(
            _issue(
                "missing_required_basket",
                f"required basket {basket_id!r} is missing",
                "baskets",
            )
        )

    actual_indices = set(bundle.indices.get("index_id", pd.Series(dtype="string")))
    for index_id in sorted(REQUIRED_INDICES - actual_indices):
        issues.append(
            _issue(
                "missing_required_index",
                f"required index {index_id!r} is missing",
                "indices",
            )
        )

    if "region" in bundle.indices.columns:
        for row_index, value in bundle.indices["region"].items():
            if _blank(value):
                issues.append(
                    _issue(
                        "index_missing_region",
                        f"indices row {row_index} is missing region",
                        "indices",
                        int(row_index),
                    )
                )
    if "display_name" in bundle.indices.columns:
        for row_index, value in bundle.indices["display_name"].items():
            if _blank(value):
                issues.append(
                    _issue(
                        "index_missing_display_name",
                        f"indices row {row_index} is missing display_name",
                        "indices",
                        int(row_index),
                    )
                )
    if {
        "official_code",
        "official_code_namespace",
        "official_code_provider",
        "provider_symbol",
        "provider_symbol_namespace",
        "provider_symbol_provider",
    } <= set(bundle.indices.columns):
        for row_index, row in bundle.indices.iterrows():
            if _blank(row["official_code"]) and _blank(row["provider_symbol"]):
                issues.append(
                    _issue(
                        "index_missing_code_or_provider_symbol",
                        f"indices row {row_index} needs official_code or provider_symbol",
                        "indices",
                        int(row_index),
                    )
                )
            if not _blank(row["official_code"]) and _blank(row["official_code_namespace"]):
                issues.append(
                    _issue(
                        "index_missing_official_code_namespace",
                        f"indices row {row_index} needs official_code_namespace",
                        "indices",
                        int(row_index),
                    )
                )
            if not _blank(row["official_code"]) and _blank(row["official_code_provider"]):
                issues.append(
                    _issue(
                        "index_missing_official_code_provider",
                        f"indices row {row_index} needs official_code_provider",
                        "indices",
                        int(row_index),
                    )
                )
            if not _blank(row["provider_symbol"]) and _blank(
                row["provider_symbol_namespace"]
            ):
                issues.append(
                    _issue(
                        "index_missing_provider_symbol_namespace",
                        f"indices row {row_index} needs provider_symbol_namespace",
                        "indices",
                        int(row_index),
                    )
                )
            if not _blank(row["provider_symbol"]) and _blank(
                row["provider_symbol_provider"]
            ):
                issues.append(
                    _issue(
                        "index_missing_provider_symbol_provider",
                        f"indices row {row_index} needs provider_symbol_provider",
                        "indices",
                        int(row_index),
                    )
                )

    if AI_BASKET_ID in actual_baskets:
        ai_members = set(
            bundle.basket_memberships.loc[
                bundle.basket_memberships["basket_id"] == AI_BASKET_ID, "entity_id"
            ]
        )
        for entity_id in sorted(REQUIRED_AI_ANCHORS - ai_members):
            issues.append(
                _issue(
                    "missing_required_ai_anchor",
                    f"required AI anchor {entity_id!r} is missing",
                    "basket_memberships",
                )
            )

    return issues
