"""Sprint 3 RxNorm normalization against live RxNorm REST API."""

from __future__ import annotations

import difflib
import json
import logging
import time
from typing import Any

import pandas as pd
import requests

from stage_a.config import REPO_ROOT
from stage_a.normalization.rxnorm_reference_service import RxNormReferenceService

logger = logging.getLogger(__name__)

RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 4
BACKOFF_SECONDS = 1.5
CACHE_PATH = REPO_ROOT / "stage_a" / "data" / "rxnorm_cache.json"
CACHE_SCHEMA_VERSION = 2
RXNORM_REFERENCE_CSV_PATH = REPO_ROOT / "stage_a" / "data" / "rxnorm_reference_corrected.csv"

ROUTE_PREFIXES = (
    "oral",
    "nasal",
    "ophthalmic",
    "otic",
    "topical",
    "transdermal",
    "rectal",
    "vaginal",
    "intravenous",
    "intramuscular",
    "subcutaneous",
    "inhalation",
    "buccal",
    "sublingual",
)


def _is_null(value: object) -> bool:
    return value is None or str(value).strip() == "" or str(value).lower().strip() == "nan"


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {
            "meta": {"schema_version": CACHE_SCHEMA_VERSION},
            "by_rxcui": {},
            "ndc_to_rxcui": {},
        }
    try:
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Invalid cache root type")
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        schema_version = meta.get("schema_version")
        if schema_version != CACHE_SCHEMA_VERSION:
            logger.warning(
                "Discarding legacy RxNorm cache at %s (schema %s != %s).",
                CACHE_PATH,
                schema_version,
                CACHE_SCHEMA_VERSION,
            )
            return {
                "meta": {"schema_version": CACHE_SCHEMA_VERSION},
                "by_rxcui": {},
                "ndc_to_rxcui": {},
            }
        raw.setdefault("by_rxcui", {})
        raw.setdefault("ndc_to_rxcui", {})
        raw.setdefault("meta", {"schema_version": CACHE_SCHEMA_VERSION})
        return raw
    except Exception as exc:
        logger.warning("Failed to read RxNorm cache file %s: %s", CACHE_PATH, exc)
        return {
            "meta": {"schema_version": CACHE_SCHEMA_VERSION},
            "by_rxcui": {},
            "ndc_to_rxcui": {},
        }


_CACHE = _load_cache()
REFERENCE_SERVICE = RxNormReferenceService(RXNORM_REFERENCE_CSV_PATH)


def _save_cache() -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE.setdefault("meta", {"schema_version": CACHE_SCHEMA_VERSION})
    _CACHE["meta"]["schema_version"] = CACHE_SCHEMA_VERSION
    CACHE_PATH.write_text(json.dumps(_CACHE, indent=2, sort_keys=True), encoding="utf-8")


def _build_url(endpoint: str, params: dict[str, str] | None = None) -> str:
    req = requests.Request("GET", f"{RXNAV_BASE}{endpoint}", params=params)
    return req.prepare().url


def _request_json(endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any] | None:
    url = _build_url(endpoint, params)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"Transient status {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            if attempt == MAX_RETRIES:
                logger.warning("RxNorm request failed after retries: %s params=%s error=%s", url, params, exc)
                return None
            sleep_seconds = BACKOFF_SECONDS ** attempt
            time.sleep(sleep_seconds)
    return None


def ndc_to_rxcui(ndc: str, existing_rxcui: str | None = None) -> str | None:
    if not _is_null(existing_rxcui):
        return str(existing_rxcui).strip()

    ndc_key = str(ndc).strip()
    if ndc_key in _CACHE["ndc_to_rxcui"]:
        return _CACHE["ndc_to_rxcui"][ndc_key]

    data = _request_json("/rxcui.json", params={"idtype": "NDC", "id": ndc_key})
    rxcui: str | None = None
    if data:
        ids = data.get("idGroup", {}).get("rxnormId")
        if isinstance(ids, list) and ids:
            rxcui = str(ids[0]).strip()

    if rxcui is None:
        logger.warning("No RxNorm RXCUI mapping found for NDC=%s", ndc_key)
    _CACHE["ndc_to_rxcui"][ndc_key] = rxcui
    _save_cache()
    return rxcui


def _concept_names_by_tty(rxcui: str) -> dict[str, list[str]]:
    data = _request_json(
        f"/rxcui/{str(rxcui).strip()}/related.json",
        params={"tty": "IN+MIN+PIN+DF+DFG"},
    )
    tty_map: dict[str, list[str]] = {}
    if not data:
        return tty_map
    groups = data.get("relatedGroup", {}).get("conceptGroup", [])
    if not isinstance(groups, list):
        return tty_map
    for group in groups:
        tty = group.get("tty")
        if not tty:
            continue
        concept_props = group.get("conceptProperties") or []
        names = []
        for concept in concept_props:
            concept_name = concept.get("name")
            if concept_name:
                names.append(str(concept_name).strip())
        tty_map[tty] = names
    return tty_map


def _fetch_related_tty(rxcui: str, tty: str, debug: bool = False) -> dict[str, Any] | None:
    endpoint = f"/rxcui/{str(rxcui).strip()}/related.json?tty={tty}"
    data = _request_json(endpoint, params=None)
    if debug:
        print(f"RXNORM_DEBUG_URL={_build_url(endpoint, None)}")
        print("RXNORM_DEBUG_RAW_JSON=")
        print(json.dumps(data, indent=2, sort_keys=True))
    return data


def _extract_tty_names(data: dict[str, Any] | None, tty: str) -> list[str]:
    if not data:
        return []
    groups = data.get("relatedGroup", {}).get("conceptGroup", [])
    if not isinstance(groups, list):
        return []
    for group in groups:
        if group.get("tty") != tty:
            continue
        props = group.get("conceptProperties") or []
        if not isinstance(props, list):
            continue
        return [str(item.get("name")).strip() for item in props if item.get("name")]
    return []


def _derive_route(tty_map: dict[str, list[str]]) -> str | None:
    dfg_values = tty_map.get("DFG") or []
    if dfg_values:
        route = dfg_values[0].replace(" Product", "").strip()
        if route:
            return route

    df_values = tty_map.get("DF") or []
    if not df_values:
        return None
    dose_form = df_values[0].lower()
    for prefix in ROUTE_PREFIXES:
        if dose_form.startswith(prefix):
            return prefix.title()
    return None


def _enrichment_for_rxcui(rxcui: str) -> dict[str, str | None]:
    rxcui_key = str(rxcui).strip()
    cached = _CACHE["by_rxcui"].get(rxcui_key)
    if isinstance(cached, dict):
        return {
            "ingredient": cached.get("ingredient"),
            "active_moiety": cached.get("active_moiety"),
            "route": cached.get("route"),
            "dose_form": cached.get("dose_form"),
        }

    ingredient_data = _fetch_related_tty(rxcui_key, tty="IN")
    ingredient_names = _extract_tty_names(ingredient_data, "IN")
    ingredient = ingredient_names[0] if ingredient_names else None

    moiety_data = _fetch_related_tty(rxcui_key, tty="MIN+PIN")
    moiety_min = _extract_tty_names(moiety_data, "MIN")
    moiety_pin = _extract_tty_names(moiety_data, "PIN")
    active_moiety = (moiety_min or moiety_pin or [None])[0]

    route_dose_data = _fetch_related_tty(rxcui_key, tty="DFG+DF")
    dfg_values = _extract_tty_names(route_dose_data, "DFG")
    df_values = _extract_tty_names(route_dose_data, "DF")
    tty_map = {"DFG": dfg_values, "DF": df_values}
    route = _derive_route(tty_map)
    dose_form = df_values[0] if df_values else None

    if ingredient is None:
        logger.warning("RxNorm ingredient (TTY=IN) missing for RXCUI=%s", rxcui_key)
    if active_moiety is None:
        logger.warning("RxNorm active moiety (TTY=MIN/PIN) missing for RXCUI=%s", rxcui_key)
    if route is None:
        logger.warning("RxNorm route missing for RXCUI=%s", rxcui_key)
    if dose_form is None:
        logger.warning("RxNorm dose form (TTY=DF) missing for RXCUI=%s", rxcui_key)

    result = {
        "ingredient": ingredient,
        "active_moiety": active_moiety,
        "route": route,
        "dose_form": dose_form,
    }
    _CACHE["by_rxcui"][rxcui_key] = result
    _save_cache()
    return result


def rxcui_to_ingredient(rxcui: str) -> str | None:
    return _enrichment_for_rxcui(rxcui).get("ingredient")


def debug_rxcui_ingredient_lookup(rxcui: str) -> str | None:
    data = _fetch_related_tty(rxcui, tty="IN", debug=True)
    names = _extract_tty_names(data, "IN")
    return names[0] if names else None


def scan_product_rxcui_consistency() -> dict[str, Any]:
    from stage_a.normalization.drug_builder import PRODUCT_DF

    mismatches: list[dict[str, Any]] = []
    total_products = len(PRODUCT_DF)
    products_with_rxcui = 0

    for idx, row in PRODUCT_DF.iterrows():
        rxcui_val = row.get("RXCUI")
        if pd.isna(rxcui_val):
            continue
        rxcui = str(rxcui_val).strip()
        if not rxcui or rxcui.lower() == "nan":
            continue

        products_with_rxcui += 1
        gnrc_nm_val = row.get("GNRC_NM")
        gnrc_nm = str(gnrc_nm_val).strip() if not pd.isna(gnrc_nm_val) else ""
        ndc_val = row.get("NDC")
        ndc = str(ndc_val).strip() if not pd.isna(ndc_val) else ""
        prod_sk_val = row.get("PROD_SK")
        product_id = int(prod_sk_val) if not pd.isna(prod_sk_val) else 0

        api_ingredient = rxcui_to_ingredient(rxcui)
        if not api_ingredient:
            mismatches.append(
                {
                    "product_id": product_id,
                    "ndc": ndc,
                    "gnrc_nm": gnrc_nm,
                    "product_rxcui": rxcui,
                    "reason": "API returned no ingredient for RXCUI",
                }
            )
            continue

        if not _drug_name_match(gnrc_nm, api_ingredient):
            fallback_rxcui = ndc_to_rxcui(ndc=ndc, existing_rxcui=None)
            mismatches.append(
                {
                    "product_id": product_id,
                    "ndc": ndc,
                    "gnrc_nm": gnrc_nm,
                    "product_rxcui": rxcui,
                    "api_ingredient_for_product_rxcui": api_ingredient,
                    "ndc_derived_rxcui": fallback_rxcui,
                    "reason": f"GNRC_NM '{gnrc_nm}' does not match API ingredient '{api_ingredient}' for RXCUI {rxcui}",
                }
            )

    return {
        "total_products": total_products,
        "products_with_rxcui": products_with_rxcui,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def _drug_name_match(name1: str | None, name2: str | None, threshold: float = 0.8) -> bool:
    if not name1 or not name2:
        return False
    clean1 = name1.strip().lower()
    clean2 = name2.strip().lower()
    if clean1 == clean2:
        return True
    if clean1 in clean2 or clean2 in clean1:
        return True
    return difflib.SequenceMatcher(None, clean1, clean2).ratio() >= threshold


def _rxcui_mismatch_log() -> dict[str, list[dict[str, str]]]:
    """Return accumulated RXCUI vs GNRC_NM mismatches as dict."""
    return getattr(_rxcui_mismatch_log, "_log", {"mismatches": []})


def _record_rxcui_mismatch(product_id: int, ndc: str, gnrc_nm: str, rxcui: str, api_ingredient: str, ndc_rxcui: str | None) -> None:
    if not hasattr(_rxcui_mismatch_log, "_log"):
        _rxcui_mismatch_log._log = {"mismatches": []}
    _rxcui_mismatch_log._log["mismatches"].append({
        "product_id": product_id,
        "ndc": ndc,
        "gnrc_nm": gnrc_nm,
        "product_rxcui": rxcui,
        "api_ingredient_for_product_rxcui": api_ingredient,
        "ndc_derived_rxcui": ndc_rxcui or "(none found)",
    })


def rxcui_to_active_moiety(rxcui: str) -> str | None:
    return _enrichment_for_rxcui(rxcui).get("active_moiety")


def rxcui_to_route(rxcui: str) -> str | None:
    return _enrichment_for_rxcui(rxcui).get("route")


def rxcui_to_dose_form(rxcui: str) -> str | None:
    return _enrichment_for_rxcui(rxcui).get("dose_form")


def normalize_drug(
    ndc: str,
    existing_rxcui: str | None = None,
    generic_name: str | None = None,
    product_id: int | None = None,
) -> dict[str, str | None]:
    def _empty_result() -> dict[str, str | None]:
        return {
            "ingredient": None,
            "active_moiety": None,
            "route": None,
            "dose_form": None,
        }

    reference_row: dict[str, Any] | None = None
    if product_id is not None:
        reference_row = REFERENCE_SERVICE.get_by_prod_sk(product_id)

    if reference_row is None and generic_name:
        reference_row = REFERENCE_SERVICE.get_by_generic_name(generic_name)

    if reference_row is None:
        logger.warning(
            "no reference entry for PROD_SK=%s - pipeline has no RxNorm data for this drug",
            product_id if product_id is not None else "unknown",
        )
        return _empty_result()

    return {
        "ingredient": reference_row.get("verified_ingredient_normalized"),
        "active_moiety": reference_row.get("verified_active_moiety_normalized"),
        "route": reference_row.get("verified_route_normalized"),
        "dose_form": reference_row.get("verified_dose_form_normalized"),
    }
