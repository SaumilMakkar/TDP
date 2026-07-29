"""Sprint 3 — RxNorm API mapper.

Responsibilities:
  - NDC  → RXCUI
  - RXCUI → Ingredient  (tty IN)
  - RXCUI → Active Moiety  (tty MIN / PIN, falls back to IN)
  - RXCUI → Route  (parsed from tty SCDF)
  - RXCUI → Dose Form  (tty DF)

All API results are cached in-memory keyed by URL so repeated lookups for
the same NDC/RXCUI within one process never hit the network twice.
Any network failure returns a partial result rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

BASE_URL = "https://rxnav.nlm.nih.gov/REST"
logger = logging.getLogger("stage_a.rxnorm")


class RxNormMapper:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Internal HTTP helper
    # ------------------------------------------------------------------ #
    def _get(self, path: str) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        if url in self._cache:
            return self._cache[url]
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("RxNorm request failed [%s]: %s", url, exc)
            data = {}
        self._cache[url] = data
        return data

    # ------------------------------------------------------------------ #
    # Mapping helpers
    # ------------------------------------------------------------------ #
    def ndc_to_rxcui(self, ndc: str) -> Optional[str]:
        """Look up RXCUI for an NDC (11-digit, no dashes)."""
        ndc_clean = ndc.replace("-", "").replace(" ", "")
        data = self._get(f"/rxcui.json?idtype=NDC&id={ndc_clean}")
        ids = data.get("idGroup", {}).get("rxnormId") or []
        return ids[0] if ids else None

    def _all_related(self, rxcui: str) -> List[Dict[str, Any]]:
        data = self._get(f"/rxcui/{rxcui}/allrelated.json")
        return data.get("allRelatedGroup", {}).get("conceptGroup", [])

    def _concepts_by_tty(self, rxcui: str, tty: str) -> List[Dict[str, Any]]:
        for group in self._all_related(rxcui):
            if group.get("tty") == tty:
                return group.get("conceptProperties") or []
        return []

    def rxcui_to_ingredients(self, rxcui: str) -> List[str]:
        return [
            c["name"].lower()
            for c in self._concepts_by_tty(rxcui, "IN")
            if c.get("name")
        ]

    def rxcui_to_active_moiety(self, rxcui: str) -> Optional[str]:
        """MIN for multi-ingredient, PIN for precise, falls back to first IN."""
        for tty in ("MIN", "PIN", "IN"):
            concepts = self._concepts_by_tty(rxcui, tty)
            if concepts:
                name = concepts[0].get("name", "")
                return name.lower() if name else None
        return None

    def rxcui_to_route(self, rxcui: str) -> Optional[str]:
        """Parse route from SCDF name e.g. 'atorvastatin Oral' → 'oral'."""
        concepts = self._concepts_by_tty(rxcui, "SCDF")
        if concepts:
            name = concepts[0].get("name", "").strip()
            parts = name.split()
            if parts:
                return parts[-1].lower()
        return None

    def rxcui_to_dose_form(self, rxcui: str) -> Optional[str]:
        concepts = self._concepts_by_tty(rxcui, "DF")
        if concepts:
            name = concepts[0].get("name", "")
            return name.lower() if name else None
        return None

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def normalize(self, ndc: str) -> Dict[str, Optional[str]]:
        """Return normalized attributes for an NDC.

        normalization_status:
          'full'    — RXCUI resolved; all fields attempted from RxNorm.
          'partial' — no RXCUI found; fields are None, caller should fall
                      back to local product table values.
        """
        rxcui = self.ndc_to_rxcui(ndc)
        if not rxcui:
            logger.info("No RXCUI found for NDC %s; returning partial.", ndc)
            return {
                "rxcui": None,
                "ingredient_norm": None,
                "active_moiety_norm": None,
                "route_norm": None,
                "dose_form_norm": None,
                "normalization_status": "partial",
            }

        ingredients = self.rxcui_to_ingredients(rxcui)
        return {
            "rxcui": rxcui,
            "ingredient_norm": ingredients[0] if ingredients else None,
            "active_moiety_norm": self.rxcui_to_active_moiety(rxcui),
            "route_norm": self.rxcui_to_route(rxcui),
            "dose_form_norm": self.rxcui_to_dose_form(rxcui),
            "normalization_status": "full",
        }
