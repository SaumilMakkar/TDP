"""
policy_agent.py — Policy Agent (Member 2)

Evaluates ONE candidate drug at a time (supplied by the Clinical Agent) against
deterministic formulary, prior-authorization, step-therapy, and quantity rules.
No LLM, no probabilistic judgment — every check is an exact lookup or comparison
against the real PBM reference tables, so a denial always traces back to a
specific rule and value.

Real data sources (flat CSV today; swap the loader functions for DB calls later
without touching the evaluation logic):
    v_d_product.csv             - drug master (active flag, validity dates, NTI/controlled flags)
    v_d_plan.csv                 - plan master (validity dates, default coverage status)
    v_d_plan_drug_status.csv     - formulary coverage, PA flag, step-therapy flag, quantity limit
    v_d_formulary_alternative.csv- step-therapy "must try first" mapping (TRGT -> ALT)
    F_CLM_TRANSACTION.csv        - member claim history (PA evidence, step-therapy evidence)

Input contract (one candidate):
    {
        "drug_id":    str   PROD_SK of the candidate drug
        "plan_id":    str   PLN_SK
        "member_id":  str   MBR_SK
        "quantity":   int   units being requested for this fill (optional)
        "fill_date":  str   ISO date, defaults to today if omitted
    }

Output contract:
    {
        "drug_id", "covered", "tier", "pa_required", "pa_met",
        "step_therapy_required", "step_therapy_met", "quantity_ok",
        "formulary_preference",
        "violations": [str, ...], "score": float, "notes": str
    }
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pbm.policy_agent")

DATA_DIR = os.environ.get(
    "PBM_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data"),
)

# Score levels. Kept coarse and explainable rather than finely tuned --
# the orchestrator's per-agent threshold (0.70, in scoring_config.json) is
# what actually decides pass/fail; these just need to land clearly on the
# correct side of that line.
SCORE_PASS = 0.95          # covered, no open PA/step-therapy/quantity issue
SCORE_FALLBACK_PASS = 0.80 # covered via plan default (no specific rule on file)
SCORE_PENDING = 0.45       # covered, but PA/step-therapy/quantity unresolved
SCORE_NOT_COVERED = 0.10   # not covered, or drug/plan/rule not valid as of fill date

# Preference hierarchy for covered options. Higher preference should receive a
# better score even when both drugs are technically covered.
PREFERENCE_SCORES = {
    "Preferred Generic": 0.98,
    "Preferred Brand": 0.90,
    "Covered": 0.84,
    "Non Preferred": 0.72,
    "Exception Only": 0.62,
    "Excluded": SCORE_NOT_COVERED,
}

PENDING_DOCTOR_REVIEW = "doctor_review"
PENDING_PRIOR_AUTH = "prior_authorization"
PENDING_STEP_THERAPY = "step_therapy"
PENDING_QUANTITY_LIMIT = "quantity_limit"


# --------------------------------------------------------------------------- #
# Data loading (cached) -- TODO: replace with a real tools/drug_db.py + DB call
# --------------------------------------------------------------------------- #
def _read_csv(name: str) -> List[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def _products() -> Dict[str, Dict[str, Any]]:
    return {r["PROD_SK"]: r for r in _read_csv("v_d_product.csv")}


@lru_cache(maxsize=1)
def _plans() -> Dict[str, Dict[str, Any]]:
    return {r["PLN_SK"]: r for r in _read_csv("v_d_plan.csv")}


@lru_cache(maxsize=1)
def _plan_drug_status() -> Dict[tuple, Dict[str, Any]]:
    # One row per (plan, drug) pair in this dataset -- no historical versioning
    # observed, but EFF_DT/TERM_DT are still honored in case that changes.
    return {(r["PLN_SK"], r["PROD_SK"]): r for r in _read_csv("v_d_plan_drug_status.csv")}


@lru_cache(maxsize=1)
def _formulary_alternatives() -> Dict[str, List[Dict[str, Any]]]:
    """TRGT_PROD_SK -> ordered list of alternative rows (by ALT_SEQ_NBR).
    Used here only to identify the step-therapy 'must try first' drug(s) for
    a given target -- the same table the Financial Agent used to use for cost
    comparison before that search moved upstream into the Clinical Agent."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in _read_csv("v_d_formulary_alternative.csv"):
        out.setdefault(r["TRGT_PROD_SK"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: int(r["ALT_SEQ_NBR"] or 0))
    return out


@lru_cache(maxsize=1)
def _claims_by_member() -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in _read_csv("F_CLM_TRANSACTION.csv"):
        out.setdefault(r["MBR_SK"], []).append(r)
    return out


def _parse_date(s: Optional[str]):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def _date_in_range(check_date: str, from_s: Optional[str], thru_s: Optional[str]) -> bool:
    d = _parse_date(check_date)
    f, t = _parse_date(from_s), _parse_date(thru_s)
    if f and d < f:
        return False
    if t and d > t:
        return False
    return True


def _plan_default_covered(plan: Dict[str, Any]) -> bool:
    return (plan.get("PLN_DFLT_DRG_STAT") or "").upper() in ("COV", "Y", "COVERED")


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _formulary_preference(product: Dict[str, Any], status: Dict[str, Any]) -> str:
    """Classify formulary preference for ranking covered options.

    Hierarchy:
      Preferred Generic > Preferred Brand > Covered > Non Preferred >
      Exception Only > Excluded
    """
    stat_cd = (status.get("PLN_DRG_STAT_CD") or "").upper()
    stat_grp = (status.get("PLN_DRG_STAT_GRP_CD") or "").upper()

    if stat_grp == "INACTIVE" or stat_cd in ("EX", "NC"):
        return "Excluded"
    if stat_cd == "NF":
        return "Exception Only"
    if stat_cd in ("PA", "ST"):
        return "Exception Only"

    tier = _safe_int(status.get("FORMULARY_TIER"))
    brand_ind = (product.get("BRAND_IND") or "").upper()
    is_generic = brand_ind not in ("Y", "1", "B")

    if tier == 1 and is_generic:
        return "Preferred Generic"
    if tier in (1, 2) and not is_generic:
        return "Preferred Brand"
    if tier is not None and tier >= 3:
        return "Non Preferred"
    return "Covered"


def _pending_score(preference: str) -> float:
    """Keep pending outcomes below approval threshold, but preserve preference order."""
    base = PREFERENCE_SCORES.get(preference, SCORE_PENDING)
    return round(max(0.20, min(0.69, base - 0.30)), 3)


def _pending_type(categories: set[str]) -> Optional[str]:
    if not categories:
        return None
    for pending_key in (PENDING_QUANTITY_LIMIT, PENDING_PRIOR_AUTH, PENDING_STEP_THERAPY, PENDING_DOCTOR_REVIEW):
        if pending_key in categories:
            return pending_key
    return next(iter(categories))


# --------------------------------------------------------------------------- #
# Evidence lookups
# --------------------------------------------------------------------------- #
def _pa_evidence(member_sk: str, prod_sk: str, plan_sk: str) -> bool:
    """A prior claim for this exact member+drug+plan with PA_APPROVED_FLG=Y
    is treated as proof prior authorization has already been granted."""
    for c in _claims_by_member().get(member_sk, []):
        if c["PROD_SK"] == prod_sk and c["PLN_SK"] == plan_sk and c.get("PA_APPROVED_FLG") == "Y":
            return True
    return False


def _step_therapy_evidence(member_sk: str, prod_sk: str) -> bool:
    """Step therapy is satisfied if the member has a prior claim for any drug
    listed as a formulary alternative to this candidate (the 'try this first'
    set). If no alternative is on file at all, there is nothing concrete to
    enforce, so treat it as satisfied rather than blocking on an undefined rule."""
    alts = _formulary_alternatives().get(prod_sk, [])
    if not alts:
        return True
    required_ids = {a["ALT_PROD_SK"] for a in alts}
    history_ids = {c["PROD_SK"] for c in _claims_by_member().get(member_sk, [])}
    return bool(required_ids & history_ids)


# --------------------------------------------------------------------------- #
# Public async interface
# --------------------------------------------------------------------------- #
async def policy_agent(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate one candidate. Offloaded to a thread so the orchestrator can
    run this concurrently with Financial and Past Decisions for the same
    candidate (and across candidates)."""
    return await asyncio.to_thread(_evaluate, candidate)


async def policy_agent_for_candidates(payload: Dict[str, Any], candidate_ids: List[str]) -> List[Dict[str, Any]]:
    """Evaluates a single claim context against multiple candidate drug IDs.

    This mirrors the orchestrator's architecture where the same plan/member/
    quantity context is applied to each alternative candidate.
    """
    tasks = [
        policy_agent({
            "drug_id": drug_id,
            "plan_id": payload["plan_id"],
            "member_id": payload.get("member_id"),
            "quantity": payload.get("quantity"),
            "fill_date": payload.get("fill_date"),
        })
        for drug_id in candidate_ids
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r.get("score", 0), reverse=True)


def _fail(
    prod_sk: str,
    reason: str,
    *,
    formulary_preference: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "drug_id": prod_sk, "covered": False, "tier": None,
        "pa_required": False, "pa_met": False,
        "step_therapy_required": False, "step_therapy_met": False,
        "quantity_ok": True,
        "formulary_preference": formulary_preference,
        "violations": [reason],
        "policy_state": "deny",
        "pending_type": None,
        "pending_reasons": [],
        "review_recommendation": None,
        "score": SCORE_NOT_COVERED,
        "notes": reason,
        "summary": {
            "decision": "deny",
            "reason": reason,
            "score": round(SCORE_NOT_COVERED, 3),
        },
    }


def _evaluate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    plan_sk = str(candidate["plan_id"])
    prod_sk = str(candidate["drug_id"])
    member_sk = str(candidate.get("member_id", ""))
    fill_date = candidate.get("fill_date") or date.today().isoformat()
    requested_qty = candidate.get("quantity")

    product = _products().get(prod_sk)
    plan = _plans().get(plan_sk)

    if product is None:
        return _fail(prod_sk, f"Unknown drug (PROD_SK={prod_sk}).")
    if plan is None:
        return _fail(prod_sk, f"Unknown plan (PLN_SK={plan_sk}).")

    if product.get("PROD_ACTV_FLG") != "Y" or not _date_in_range(
        fill_date, product.get("PROD_EFF_DT"), product.get("PROD_TERM_DT")
    ):
        return _fail(
            prod_sk,
            f"Drug {prod_sk} is not active as of {fill_date}.",
        )

    if not _date_in_range(fill_date, plan.get("PLN_EFF_DT"), plan.get("PLN_TERM_DT")):
        return _fail(prod_sk, f"Plan {plan_sk} is not active as of {fill_date}.")

    status = _plan_drug_status().get((plan_sk, prod_sk))

    # No specific formulary rule on file for this (plan, drug) pair -> fall
    # back to the plan's stated default coverage status.
    if status is None or not _date_in_range(fill_date, status.get("EFF_DT"), status.get("TERM_DT")):
        if not _plan_default_covered(plan):
            reason = (
                f"No formulary rule on file for ({plan_sk}, {prod_sk}); plan default is non-covered."
                if status is None else
                f"Formulary rule for ({plan_sk}, {prod_sk}) expired as of {fill_date}; plan default is non-covered."
            )
            return _fail(
                prod_sk,
                reason,
                formulary_preference="Excluded",
            )
        return {
            "drug_id": prod_sk, "covered": True, "tier": None,
            "pa_required": False, "pa_met": True,
            "step_therapy_required": False, "step_therapy_met": True,
            "quantity_ok": True,
            "formulary_preference": "Covered",
            "violations": [],
            "policy_state": "pass",
            "pending_type": None,
            "pending_reasons": [],
            "review_recommendation": None,
            "score": SCORE_FALLBACK_PASS,
            "notes": "Covered under plan default (no specific formulary rule on file).",
            "summary": {
                "decision": "pass",
                "reason": "Covered under plan default.",
                "score": round(SCORE_FALLBACK_PASS, 3),
            },
        }

    # PLN_DRG_STAT_CD is a single status code, not an independent overlay on
    # top of a generic "covered" flag. The real vocabulary observed in this
    # dataset is:
    #   ACTIVE group:     COV (plain covered), SP (specialty, still covered)
    #   RESTRICTED group: QL (quantity limit), NF (non-formulary),
    #                      ST (step therapy required), PA (PA required)
    #   INACTIVE group:   EX (excluded), NC (not covered)
    # PA_REQUIRED_FLG / STEP_THERAPY_FLG / QUANTITY_LIMIT are each only
    # populated on the one status code they correspond to (PA, ST, QL
    # respectively) -- they are not independent flags layered on a COV row.
    stat_cd = status.get("PLN_DRG_STAT_CD")
    stat_grp = status.get("PLN_DRG_STAT_GRP_CD")
    tier = status.get("FORMULARY_TIER")

    if stat_grp == "INACTIVE" or stat_cd in ("EX", "NC"):
        desc = status.get("PLN_DRG_STAT_DESC", stat_cd)
        return _fail(
            prod_sk,
            f"{prod_sk} is {desc.lower()} under plan {plan_sk} (status {stat_cd}).",
            formulary_preference="Excluded",
        )

    if stat_cd == "NF":
        # Non-formulary: technically "RESTRICTED" rather than "INACTIVE" in
        # this dataset's grouping, but there is no standard coverage pathway
        # modeled for it here (no PA/step/qty condition that, once satisfied,
        # makes it payable) -- treated as effectively not covered.
        return _fail(
            prod_sk,
            f"{prod_sk} is non-formulary under plan {plan_sk}; no standard coverage pathway.",
            formulary_preference="Exception Only",
        )

    violations: List[str] = []
    pending_categories: set[str] = set()

    pa_required = stat_cd == "PA"
    pa_met = True
    if pa_required:
        pa_met = _pa_evidence(member_sk, prod_sk, plan_sk)
        if not pa_met:
            violations.append("Prior authorization required and not yet evidenced.")
            pending_categories.add(PENDING_PRIOR_AUTH)

    step_required = stat_cd == "ST"
    step_met = True
    if step_required:
        step_met = _step_therapy_evidence(member_sk, prod_sk)
        if not step_met:
            violations.append("Step therapy required; no evidence the qualifying alternative was tried first.")
            pending_categories.add(PENDING_STEP_THERAPY)

    quantity_ok = True
    if stat_cd == "QL":
        qty_limit_raw = (status.get("QUANTITY_LIMIT") or "").strip()
        if qty_limit_raw and requested_qty is not None:
            try:
                qty_limit = int(qty_limit_raw)
                if int(requested_qty) > qty_limit:
                    quantity_ok = False
                    violations.append(f"Requested quantity {requested_qty} exceeds plan limit {qty_limit}.")
                    pending_categories.add(PENDING_QUANTITY_LIMIT)
            except ValueError:
                logger.warning("Non-numeric QUANTITY_LIMIT '%s' for (%s, %s); skipping check.",
                                qty_limit_raw, plan_sk, prod_sk)

    # COV and SP fall through here with no condition to check -- violations
    # stays empty and they score as a clean pass, same as a satisfied
    # PA/ST/QL condition.

    preference = _formulary_preference(product, status)
    score = PREFERENCE_SCORES.get(preference, SCORE_PASS) if not violations else _pending_score(preference)
    decision = "pass" if not violations else "pending"
    policy_state = decision
    pending_type = _pending_type(pending_categories)
    pending_reasons = list(violations) if decision == "pending" else []
    review_recommendation = None
    if decision == "pending":
        if pending_type in (PENDING_DOCTOR_REVIEW, PENDING_PRIOR_AUTH, PENDING_STEP_THERAPY, PENDING_QUANTITY_LIMIT):
            review_recommendation = "Doctor review required (accept/reject/modify)."
    summary_reason = "; ".join(violations) if violations else f"{preference} formulary preference. All policy checks passed."

    return {
        "drug_id": prod_sk,
        "covered": True,
        "tier": status.get("FORMULARY_TIER"),
        "pa_required": pa_required,
        "pa_met": pa_met,
        "step_therapy_required": step_required,
        "step_therapy_met": step_met,
        "quantity_ok": quantity_ok,
        "formulary_preference": preference,
        "violations": violations,
        "policy_state": policy_state,
        "pending_type": pending_type,
        "pending_reasons": pending_reasons,
        "review_recommendation": review_recommendation,
        "score": round(score, 3),
        "notes": "; ".join(violations) if violations else f"{preference} formulary preference. All policy checks passed.",
        "summary": {
            "decision": decision,
            "reason": summary_reason,
            "score": round(score, 3),
        },
    }


# --------------------------------------------------------------------------- #
# Local smoke test: python -m app.agents.policy_agent
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import json

    async def _demo():
        # Same claim context, 3 alternatives -- aligned with orchestrator flow.
        claim = {
            "drug_id": "1018",  # original (shown for context)
            "plan_id": "3010",
            "member_id": "2001",
            "quantity": 30,
            "fill_date": "2025-06-01",
        }
        alternatives = ["1033", "1011", "1008"]
        results = await policy_agent_for_candidates(claim, alternatives)
        for drug_id, result in zip(alternatives, results):
            print(json.dumps({
                "claim_context": claim,
                "candidate_drug_id": drug_id,
                "result": result,
            }, indent=2))

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_demo())
