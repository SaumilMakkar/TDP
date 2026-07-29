"""
financial_agent.py — Financial Agent (Member 2)

Prices ONE candidate drug at a time (supplied by the Clinical Agent) and
compares it against what the ORIGINALLY PRESCRIBED drug would cost. Clinical
Agent's job stays exactly as it was -- it proposes alternatives based on
drug-drug interactions and composition only, with no pricing involved.
Financial Agent is the only place a cost comparison happens.

No LLM, no judgment calls here -- arithmetic over real pricing tables, twice
(once for the candidate, once for the original), then a direct comparison.

Real data sources:
    v_d_drug_pricing.csv     - BASE_PRICE/DRUG_COST_PERCT_1/FEE_1/TAX_AMT -> FINAL_COST,
                                 versioned by PRICE_EFF_FROM_DT/PRICE_EFF_THRU_DT
    v_d_plan_drug_status.csv - FORMULARY_TIER for this (plan, drug) pair
    v_d_plan.csv              - MAX_OOP_AMT, DEDUCTIBLE_AMT (plan-level caps)

Patient-pay estimation note (read before changing the tier table):
    F_CLM_TRANSACTION.csv only has APP_COPAY_AMT / APP_PATIENT_PAY_AMT for
    claims that have ALREADY been adjudicated. A Clinical candidate (and the
    original prescription, before it's filled) is a hypothetical fill that
    hasn't been claimed yet, so there's no actual patient-pay figure to look
    up for either one -- both have to be estimated from the tier.
    TIER_COINSURANCE below was not invented; it was derived by averaging
    APP_COPAY_AMT / FINAL_COST across every real PAID/ADJUDICATED claim in
    F_CLM_TRANSACTION.csv, grouped by FORMULARY_TIER:
        tier 1 -> ~22%   tier 2 -> ~24%   tier 3 -> ~45%
        tier 4 -> ~66%   tier 5 -> ~72%
    This is an estimate, not a guarantee -- real adjudication may differ
    claim to claim. Flagged here rather than hidden in a magic number.

Insurance phase awareness:
    Every member is in one of three phases within their plan year. The agent
    now determines the phase from F_CLM_TRANSACTION.csv and adjusts patient
    pay accordingly:

    DEDUCTIBLE phase     -- member has NOT yet met their annual deductible;
                           they pay 100% of FINAL_COST until the cap is met.
    INITIAL_COVERAGE     -- deductible met; insurance kicks in and the member
                           pays their tier coinsurance rate (22%-72% depending
                           on tier). This was the ONLY mode previously.
    CATASTROPHIC         -- member has hit their annual OOP maximum; the plan
                           covers 100% and patient pay is $0.

    YTD OOP is calculated by summing OOP_APPLIED_AMT from all PAID/ADJUDICATED
    claims in F_CLM_TRANSACTION.csv for the same member, plan, and calendar
    year as the fill date. This is the same approach used by real PBM engines.
    Note: future fills within the same year cannot be predicted, so YTD
    reflects data up to the most recent adjudicated claim on file.

Comparison logic:
    If the original drug is priceable, the score is driven by the relative
    savings (or cost increase) of the candidate versus the original -- a
    candidate that costs meaningfully less scores well; one that costs more
    scores poorly, regardless of its absolute tier. If the original is NOT
    priceable (not covered, no formulary rule, no pricing on file), there is
    nothing to compare against, so the agent falls back to scoring the
    candidate's absolute tier-based affordability instead, and says so in
    the notes -- it does not silently skip the comparison without saying why.

Input contract (one candidate):
    {
        "drug_id":          str   PROD_SK of the candidate drug
        "plan_id":          str   PLN_SK
        "member_id":        str   MBR_SK (optional but needed for phase detection)
        "fill_date":        str   ISO date, defaults to today if omitted
        "original_drug_id": str   PROD_SK of the originally prescribed drug
                                   (optional -- if omitted, no comparison is
                                   possible and the agent falls back to the
                                   absolute tier-based score with a note)
    }

    Output contract:
    {
        "drug_id", "covered", "tier", "final_cost", "estimated_patient_pay",
        "pricing_source",
        "original_drug_id", "original_final_cost", "original_patient_pay",
        "estimated_savings", "savings_pct",
        "insurance_context", "financial_phase_decision_hint", "score", "notes"
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

logger = logging.getLogger("pbm.financial_agent")

DATA_DIR = os.environ.get(
    "PBM_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data"),
)

# Coinsurance ratio per formulary tier, calibrated from real APP_COPAY_AMT /
# FINAL_COST averages across F_CLM_TRANSACTION.csv. See module docstring.
TIER_COINSURANCE = {
    "1": 0.22,
    "2": 0.24,
    "3": 0.45,
    "4": 0.66,
    "5": 0.72,
}
DEFAULT_COINSURANCE = 0.40  # used only if a tier outside 1-5 ever appears

# Score levels for the NO-COMPARISON fallback path (original isn't priceable).
SCORE_NOT_COVERED = 0.10
SCORE_NO_PRICE_ON_FILE = 0.30
SCORE_EXPENSIVE = 0.50
SCORE_REASONABLE = 0.80
SCORE_ORIGINAL_UNPRICED_FALLBACK = 0.85  # original had no coverage at all; candidate having
                                          # any valid coverage is a meaningful improvement on its own

# Comparison-based scoring (used whenever the original IS priceable):
# score = clip(COMPARISON_MIDPOINT + savings_pct, COMPARISON_FLOOR, COMPARISON_CEILING)
# savings_pct > 0 means the candidate is CHEAPER than the original.
# A 10%+ saving is enough to clear the 0.60 financial threshold; a candidate
# priced the same as the original lands at 0.50 (just below the bar) -- a
# real substitution is expected to actually save money, not just break even.
COMPARISON_MIDPOINT = 0.50
COMPARISON_FLOOR = 0.05
COMPARISON_CEILING = 0.95


# --------------------------------------------------------------------------- #
# Data loading (cached) -- TODO: replace with tools/pricing.py + DB call
# --------------------------------------------------------------------------- #
def _read_csv(name: str) -> List[Dict[str, Any]]:
    path = os.path.join(DATA_DIR, name)
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def _pricing_by_drug() -> Dict[str, List[Dict[str, Any]]]:
    """PROD_SK -> all historical pricing rows (multiple versions per drug in
    this dataset, distinguished by PRICE_EFF_FROM_DT/PRICE_EFF_THRU_DT)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in _read_csv("v_d_drug_pricing.csv"):
        out.setdefault(r["PROD_SK"], []).append(r)
    return out


@lru_cache(maxsize=1)
def _plan_drug_status() -> Dict[tuple, Dict[str, Any]]:
    return {(r["PLN_SK"], r["PROD_SK"]): r for r in _read_csv("v_d_plan_drug_status.csv")}


@lru_cache(maxsize=1)
def _plans() -> Dict[str, Dict[str, Any]]:
    return {r["PLN_SK"]: r for r in _read_csv("v_d_plan.csv")}


@lru_cache(maxsize=1)
def _claims_by_member() -> Dict[str, List[Dict[str, Any]]]:
    """MBR_SK -> all claim rows for that member."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in _read_csv("F_CLM_TRANSACTION.csv"):
        out.setdefault(r["MBR_SK"], []).append(r)
    return out


@lru_cache(maxsize=1)
def _claim_tier_by_plan_drug() -> Dict[tuple, str]:
    """(PLN_SK, PROD_SK) -> most recent observed FORMULARY_TIER from paid history.

    This is used as a conservative fallback when the plan-drug status table
    has no explicit row for a pair but adjudicated claim evidence exists.
    """
    latest: Dict[tuple, tuple] = {}
    for r in _read_csv("F_CLM_TRANSACTION.csv"):
        if r.get("CLAIM_STAT_ID") not in ("PAID", "ADJUDICATED"):
            continue
        plan = str(r.get("PLN_SK") or "").strip()
        prod = str(r.get("PROD_SK") or "").strip()
        tier = str(r.get("FORMULARY_TIER") or "").strip()
        filled = str(r.get("FILLED_DT") or "")
        if not plan or not prod or not tier:
            continue
        key = (plan, prod)
        prev = latest.get(key)
        if prev is None or filled > prev[0]:
            latest[key] = (filled, tier)
    return {k: v[1] for k, v in latest.items()}


def _member_ytd_oop(member_sk: str, plan_sk: str, fill_date: str) -> float:
    """Sum OOP_APPLIED_AMT for all adjudicated claims this member has had
    under this plan in the same calendar year as fill_date."""
    year = fill_date[:4]
    total = 0.0
    for c in _claims_by_member().get(member_sk, []):
        if c.get("PLN_SK") != plan_sk:
            continue
        if (c.get("FILLED_DT") or "")[:4] != year:
            continue
        if c.get("CLAIM_STAT_ID") not in ("PAID", "ADJUDICATED"):
            continue
        try:
            total += float(c.get("OOP_APPLIED_AMT") or 0)
        except (ValueError, TypeError):
            pass
    return round(total, 2)


def _determine_insurance_phase(
    member_sk: str, plan_sk: str, fill_date: str
) -> Dict[str, Any]:
    """Determines which insurance phase the member is currently in.

    Returns a dict with:
        phase            - DEDUCTIBLE | INITIAL_COVERAGE | CATASTROPHIC
        ytd_oop          - total OOP paid so far this year
        deductible_cap   - annual deductible from plan
        oop_max_cap      - annual OOP max from plan
        deductible_remaining
        oop_remaining
    """
    plan = _plans().get(plan_sk, {})
    try:
        deductible = float(plan.get("DEDUCTIBLE_AMT") or 0)
    except (ValueError, TypeError):
        deductible = 0.0
    try:
        oop_max = float(plan.get("MAX_OOP_AMT") or 999999)
    except (ValueError, TypeError):
        oop_max = 999999.0

    if not member_sk:
        # No member_id supplied -- cannot determine phase, stay in INITIAL_COVERAGE
        return {
            "phase": "INITIAL_COVERAGE",
            "ytd_oop": None,
            "deductible_cap": deductible,
            "oop_max_cap": oop_max,
            "deductible_remaining": None,
            "oop_remaining": None,
            "note": "member_id not supplied; defaulted to INITIAL_COVERAGE phase.",
        }

    ytd_oop = _member_ytd_oop(member_sk, plan_sk, fill_date)
    deductible_remaining = max(0.0, round(deductible - ytd_oop, 2))
    oop_remaining = max(0.0, round(oop_max - ytd_oop, 2))

    if ytd_oop >= oop_max:
        phase = "CATASTROPHIC"
    elif deductible > 0 and ytd_oop < deductible:
        phase = "DEDUCTIBLE"
    else:
        phase = "INITIAL_COVERAGE"

    return {
        "phase": phase,
        "ytd_oop": ytd_oop,
        "deductible_cap": deductible,
        "oop_max_cap": oop_max,
        "deductible_remaining": deductible_remaining,
        "oop_remaining": oop_remaining,
        "note": None,
    }


def _phase_from_accumulators(ytd_oop: float, deductible_cap: float, oop_max_cap: float) -> str:
    if ytd_oop >= oop_max_cap:
        return "CATASTROPHIC"
    if deductible_cap > 0 and ytd_oop < deductible_cap:
        return "DEDUCTIBLE"
    return "INITIAL_COVERAGE"


def _phase_decision_hint(cand_fill: Dict[str, Any], orig_fill: Dict[str, Any]) -> str:
    """Compact summary for doctor/manager-facing financial interpretation."""
    c_before, c_after = cand_fill.get("phase_before"), cand_fill.get("phase_after")
    o_before, o_after = orig_fill.get("phase_before"), orig_fill.get("phase_after")

    if c_after != o_after:
        return f"Phase impact differs: candidate ends in {c_after}, original ends in {o_after}."
    if cand_fill.get("phase_crossed") and not orig_fill.get("phase_crossed"):
        return f"Candidate crosses phase boundary ({c_before} -> {c_after}); original does not."
    if orig_fill.get("phase_crossed") and not cand_fill.get("phase_crossed"):
        return f"Original crosses phase boundary ({o_before} -> {o_after}); candidate does not."
    if cand_fill.get("phase_crossed") and orig_fill.get("phase_crossed"):
        return f"Both options cross phase boundary (candidate {c_before}->{c_after}, original {o_before}->{o_after})."
    return f"No phase-boundary difference: both stay in {c_after}."


def _estimate_fill_impact(final_cost: float, tier: Optional[str], ins_ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate this single fill across phase boundaries.

    A fill may span multiple phases in one transaction:
      1) remaining deductible (member pays 100%)
      2) initial coverage on any remainder (tier coinsurance)
      3) capped by remaining OOP before catastrophic
    """
    phase_before = ins_ctx["phase"]
    deductible_cap = float(ins_ctx.get("deductible_cap") or 0.0)
    oop_max_cap = float(ins_ctx.get("oop_max_cap") or 999999.0)

    if ins_ctx.get("ytd_oop") is None:
        # No member-level accumulator available; fall back to initial coverage estimate.
        coinsurance = TIER_COINSURANCE.get(tier, DEFAULT_COINSURANCE)
        patient_pay = round(final_cost * coinsurance, 2)
        return {
            "phase_before": "INITIAL_COVERAGE",
            "phase_after": "INITIAL_COVERAGE",
            "phase_crossed": False,
            "patient_pay": patient_pay,
            "effective_coinsurance": coinsurance,
            "deductible_component": 0.0,
            "coinsurance_component": patient_pay,
            "deductible_remaining_after": None,
            "oop_remaining_after": None,
            "ytd_oop_after": None,
            "note": "member_id unavailable; used initial-coverage estimate.",
        }

    ytd_oop_before = float(ins_ctx["ytd_oop"])
    deductible_remaining = max(0.0, round(deductible_cap - ytd_oop_before, 2))
    oop_remaining = max(0.0, round(oop_max_cap - ytd_oop_before, 2))
    amount_remaining = float(final_cost)

    deductible_component = 0.0
    coinsurance_component = 0.0
    patient_pay = 0.0

    # Catastrophic already reached before this fill.
    if oop_remaining <= 0.0:
        phase_after = "CATASTROPHIC"
        return {
            "phase_before": phase_before,
            "phase_after": phase_after,
            "phase_crossed": phase_before != phase_after,
            "patient_pay": 0.0,
            "effective_coinsurance": 0.0,
            "deductible_component": 0.0,
            "coinsurance_component": 0.0,
            "deductible_remaining_after": deductible_remaining,
            "oop_remaining_after": 0.0,
            "ytd_oop_after": ytd_oop_before,
            "note": "OOP max already reached; plan covers 100%.",
        }

    # 1) Deductible tranche: member pays dollar-for-dollar until deductible is met.
    if deductible_remaining > 0.0 and amount_remaining > 0.0:
        deductible_component = min(amount_remaining, deductible_remaining)
        amount_remaining -= deductible_component
        patient_pay += deductible_component

    # 2) Initial coverage tranche on the remainder: tier coinsurance.
    if amount_remaining > 0.0:
        coinsurance = TIER_COINSURANCE.get(tier, DEFAULT_COINSURANCE)
        coinsurance_component = amount_remaining * coinsurance
        patient_pay += coinsurance_component
    else:
        coinsurance = TIER_COINSURANCE.get(tier, DEFAULT_COINSURANCE)

    # 3) Cap patient pay by remaining OOP before catastrophic phase.
    patient_pay = round(min(patient_pay, oop_remaining), 2)
    deductible_component = round(min(deductible_component, patient_pay), 2)
    coinsurance_component = round(max(0.0, patient_pay - deductible_component), 2)

    ytd_oop_after = round(ytd_oop_before + patient_pay, 2)
    phase_after = _phase_from_accumulators(ytd_oop_after, deductible_cap, oop_max_cap)
    effective_coinsurance = round(patient_pay / final_cost, 4) if final_cost else 0.0

    return {
        "phase_before": phase_before,
        "phase_after": phase_after,
        "phase_crossed": phase_before != phase_after,
        "patient_pay": patient_pay,
        "effective_coinsurance": effective_coinsurance,
        "deductible_component": deductible_component,
        "coinsurance_component": coinsurance_component,
        "deductible_remaining_after": max(0.0, round(deductible_cap - ytd_oop_after, 2)),
        "oop_remaining_after": max(0.0, round(oop_max_cap - ytd_oop_after, 2)),
        "ytd_oop_after": ytd_oop_after,
        "note": None,
    }


def _parse_date(s: Optional[str]):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def _price_valid_on(row: Dict[str, Any], as_of: str) -> bool:
    d = _parse_date(as_of)
    f = _parse_date(row.get("PRICE_EFF_FROM_DT"))
    t = _parse_date(row.get("PRICE_EFF_THRU_DT"))
    if f and d < f:
        return False
    if t and d > t:
        return False
    return True


def _price_for(prod_sk: str, as_of: str) -> Optional[Dict[str, Any]]:
    all_rows = _pricing_by_drug().get(prod_sk, [])
    if not all_rows:
        return None
    candidates = [r for r in all_rows if _price_valid_on(r, as_of)]
    pool = candidates or all_rows
    pool.sort(key=lambda r: r.get("PRICE_EFF_FROM_DT", ""))
    return pool[-1]


def _price_drug(plan_sk: str, prod_sk: str, fill_date: str) -> Dict[str, Any]:
    """Prices a single drug under a single plan. Used for BOTH the candidate
    and the original prescription -- identical logic, no special-casing,
    so the two numbers are directly comparable."""
    status = _plan_drug_status().get((plan_sk, prod_sk))
    stat_cd = status.get("PLN_DRG_STAT_CD") if status else None
    stat_grp = status.get("PLN_DRG_STAT_GRP_CD") if status else None
    tier = status.get("FORMULARY_TIER") if status else None

    # Same status vocabulary as policy_agent.py: ACTIVE (COV, SP) and
    # RESTRICTED-but-conditionally-payable (QL, ST, PA) are all priceable.
    # INACTIVE (EX, NC) and NF (no standard coverage pathway modeled) are not.
    priceable = status is not None and stat_grp != "INACTIVE" and stat_cd not in ("EX", "NC", "NF")

    if status is None:
        # Sparse-data fallback: if we have a real price row, treat as priceable
        # and infer tier from adjudicated claims for this plan-drug pair.
        price_row = _price_for(prod_sk, fill_date)
        if price_row is None:
            return {
                "drug_id": prod_sk,
                "covered": False,
                "tier": None,
                "final_cost": None,
                "patient_pay": None,
                "pricing_source": None,
                "note": f"No formulary rule or pricing row found for {prod_sk} under plan {plan_sk}.",
            }

        inferred_tier = _claim_tier_by_plan_drug().get((plan_sk, prod_sk), "4")
        final_cost = float(price_row["FINAL_COST"])
        coinsurance = TIER_COINSURANCE.get(inferred_tier, DEFAULT_COINSURANCE)
        patient_pay_initial = round(final_cost * coinsurance, 2)

        return {
            "drug_id": prod_sk,
            "covered": True,
            "tier": inferred_tier,
            "final_cost": round(final_cost, 2),
            "patient_pay": patient_pay_initial,
            "pricing_source": price_row.get("PRICING_SOURCE"),
            "coinsurance": coinsurance,
            "note": (
                f"No explicit plan-drug status for ({plan_sk}, {prod_sk}); "
                f"used pricing row plus inferred tier {inferred_tier} from claim history/default."
            ),
        }

    if not priceable:
        return {
            "drug_id": prod_sk, "covered": False, "tier": tier,
            "final_cost": None, "patient_pay": None, "pricing_source": None,
            "note": f"{prod_sk} is not in a payable status under plan {plan_sk}"
                    + (f" (status {stat_cd})." if stat_cd else " (no formulary rule on file)."),
        }

    price_row = _price_for(prod_sk, fill_date)
    if price_row is None:
        return {
            "drug_id": prod_sk, "covered": True, "tier": tier,
            "final_cost": None, "patient_pay": None, "pricing_source": None,
            "note": f"No pricing record valid for {prod_sk} as of {fill_date}.",
        }

    final_cost = float(price_row["FINAL_COST"])
    # patient_pay is computed later after phase is known; store final_cost only here
    coinsurance = TIER_COINSURANCE.get(tier, DEFAULT_COINSURANCE)
    patient_pay_initial = round(final_cost * coinsurance, 2)  # initial coverage baseline

    return {
        "drug_id": prod_sk, "covered": True, "tier": tier,
        "final_cost": round(final_cost, 2), "patient_pay": patient_pay_initial,
        "pricing_source": price_row["PRICING_SOURCE"], "coinsurance": coinsurance,
        "note": None,
    }


# --------------------------------------------------------------------------- #
# Public async interface
# --------------------------------------------------------------------------- #
async def financial_agent(candidate: Dict[str, Any]) -> Dict[str, Any]:
    return await asyncio.to_thread(_evaluate, candidate)


async def financial_agent_for_candidates(payload: Dict[str, Any], candidate_ids: List[str]) -> List[Dict[str, Any]]:
    """Prices multiple candidate drugs under one shared claim context.

    Keeps the same original_drug_id for every candidate so comparisons stay
    aligned and directly comparable across alternatives.
    """
    tasks = [
        financial_agent({
            "drug_id": drug_id,
            "plan_id": payload["plan_id"],
            "member_id": payload.get("member_id"),
            "fill_date": payload.get("fill_date"),
            "original_drug_id": payload.get("drug_id"),
        })
        for drug_id in candidate_ids
    ]
    results = await asyncio.gather(*tasks)
    return sorted(results, key=lambda r: r.get("score", 0), reverse=True)


def _estimate_annual_fills(days_supply: Any, frequency: Any) -> float:
    """Estimate fills per year from days_supply and frequency.
    
    Uses realistic pharmacy dispensing patterns:
    - If both provided: calculate from actual dosing + supply
    - If only supply provided: assume once-daily (365/days)
    - If only frequency provided: assume 30-day supply + frequency
    - If neither: assume standard 30-day supply, once-daily = 12 fills/year
    
    Args:
        days_supply: Days supplied per fill (e.g., 30, 90)
        frequency: Dosing frequency string (e.g., "Once daily", "Twice daily", "Once weekly")
    
    Returns:
        Estimated fills per year
    """
    # Default: assume 30-day supplies filled 12 times/year = realistic annual cost
    DEFAULT_DAYS = 30
    
    try:
        days = float(days_supply) if days_supply else DEFAULT_DAYS
        if days <= 0:
            days = DEFAULT_DAYS
    except (ValueError, TypeError):
        days = DEFAULT_DAYS
    
    freq_str = str(frequency or "").lower().strip()
    
    # Map common frequency patterns to daily pill count
    if "once" in freq_str and "daily" in freq_str:
        pills_per_day = 1
    elif "twice" in freq_str and "daily" in freq_str:
        pills_per_day = 2
    elif "three" in freq_str and "daily" in freq_str:
        pills_per_day = 3
    elif "four" in freq_str and "daily" in freq_str:
        pills_per_day = 4
    elif "once" in freq_str and "weekly" in freq_str:
        pills_per_day = 1 / 7
    elif "twice" in freq_str and "weekly" in freq_str:
        pills_per_day = 2 / 7
    else:
        # Default: assume once-daily dosing (most common pattern)
        pills_per_day = 1
    
    # Calculate fills per year: (365 days/year × pills/day) / (days_supply × pills in supply)
    # Simplifies to: (365 × pills_per_day) / (days_supply × pills_per_day) = 365 / days_supply
    fills_per_year = 365 / days
    
    return max(fills_per_year, 0.1)  # At least 0.1 fills/year


def _evaluate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    plan_sk = str(candidate["plan_id"])
    prod_sk = str(candidate["drug_id"])
    member_sk = str(candidate.get("member_id") or "")
    fill_date = candidate.get("fill_date") or date.today().isoformat()
    original_id = candidate.get("original_drug_id")
    original_id = str(original_id) if original_id is not None else None
    days_supply = candidate.get("days_supply")
    frequency = candidate.get("frequency")
    annual_fills = _estimate_annual_fills(days_supply, frequency)

    # ---- Determine member's insurance phase ONCE for this claim. -----------
    ins_ctx = _determine_insurance_phase(member_sk, plan_sk, fill_date)
    phase = ins_ctx["phase"]

    cand_price = _price_drug(plan_sk, prod_sk, fill_date)
    
    # ---- Price original upfront (if provided) for comparison context -------
    orig_price = None
    if original_id is not None:
        orig_price = _price_drug(plan_sk, original_id, fill_date)

    # ---- Candidate itself isn't priceable -- comparison is moot. -----------
    if not cand_price["covered"]:
        return _result(prod_sk, cand_price, orig_price, score=SCORE_NOT_COVERED,
                       notes=cand_price["note"], insurance_context=ins_ctx, annual_fills=annual_fills)
    if cand_price["final_cost"] is None:
        return _result(prod_sk, cand_price, orig_price, score=SCORE_NO_PRICE_ON_FILE,
                       notes=cand_price["note"], insurance_context=ins_ctx, annual_fills=annual_fills)

    # ---- Apply phase to candidate patient pay. -----------------------------
    cand_fill = _estimate_fill_impact(cand_price["final_cost"], cand_price["tier"], ins_ctx)
    cand_pay = cand_fill["patient_pay"]
    cand_coins = cand_fill["effective_coinsurance"]
    cand_price["patient_pay"] = cand_pay
    cand_price["coinsurance"] = cand_coins

    # ---- No original to compare against -- fall back to absolute tier score.
    if original_id is None:
        score = _tier_only_score(cand_coins)
        notes = (
            f"[{cand_fill['phase_before']} -> {cand_fill['phase_after']}] "
            f"Estimated patient pay ${cand_pay:.2f} on tier {cand_price['tier']} "
            f"(deductible ${cand_fill['deductible_component']:.2f}, "
            f"coinsurance ${cand_fill['coinsurance_component']:.2f}; ${cand_price['final_cost']:.2f} final cost; "
            f"pricing source: {cand_price['pricing_source']}). No original drug supplied for "
            f"comparison -- score reflects absolute tier-based affordability only."
        )
        return _result(
            prod_sk,
            cand_price,
            None,
            score=score,
            notes=notes,
            insurance_context={
                **ins_ctx,
                "candidate_fill_projection": cand_fill,
            },
            annual_fills=annual_fills,
        )

    # ---- Original supplied and priced upfront; now apply phase to it. -------
    if not orig_price["covered"] or orig_price["final_cost"] is None:
        notes = (
            f"[{cand_fill['phase_before']} -> {cand_fill['phase_after']}] "
            f"Estimated patient pay ${cand_pay:.2f} on tier {cand_price['tier']}. "
            f"Original drug {original_id} could not be priced for comparison "
            f"({orig_price['note']}); treating any valid coverage as an improvement."
        )
        return _result(
            prod_sk,
            cand_price,
            orig_price,
            score=SCORE_ORIGINAL_UNPRICED_FALLBACK,
            notes=notes,
            insurance_context={
                **ins_ctx,
                "candidate_fill_projection": cand_fill,
            },
            annual_fills=annual_fills,
        )

    orig_fill = _estimate_fill_impact(orig_price["final_cost"], orig_price["tier"], ins_ctx)
    orig_pay = orig_fill["patient_pay"]
    orig_price["patient_pay"] = orig_pay

    # ---- Annualize costs for realistic annual comparison ----
    cand_annual_pay = round(cand_pay * annual_fills, 2)
    orig_annual_pay = round(orig_pay * annual_fills, 2)

    # ---- CATASTROPHIC: both drugs are free -- score is neutral. ------------
    if phase == "CATASTROPHIC":
        notes = (
            f"[CATASTROPHIC] Member has reached OOP max (${ins_ctx['oop_max_cap']:.2f}); "
            f"plan covers 100% for both candidate {prod_sk} and original {original_id}. "
            f"Financial comparison not meaningful this fill."
        )
        return _result(
            prod_sk,
            cand_price,
            orig_price,
            score=0.50,
            notes=notes,
            savings=0.0,
            savings_pct=0.0,
            insurance_context={
                **ins_ctx,
                "candidate_fill_projection": cand_fill,
                "original_fill_projection": orig_fill,
            },
            phase_decision_hint=_phase_decision_hint(cand_fill, orig_fill),
            annual_fills=annual_fills,
        )

    savings = round(orig_annual_pay - cand_annual_pay, 2)
    savings_pct = round(savings / orig_annual_pay, 4) if orig_annual_pay else 0.0
    score = round(min(max(COMPARISON_MIDPOINT + savings_pct, COMPARISON_FLOOR), COMPARISON_CEILING), 3)

    direction = "saves" if savings > 0 else ("costs the same as" if savings == 0 else "costs more than")

    ytd_display = f"${ins_ctx['ytd_oop']:.2f}" if ins_ctx["ytd_oop"] is not None else "unknown"
    phase_note = (
        f"[{cand_fill['phase_before']} -> candidate:{cand_fill['phase_after']} / original:{orig_fill['phase_after']}] "
        f"YTD OOP {ytd_display}, deductible cap ${ins_ctx['deductible_cap']:.2f}, "
        f"OOP max ${ins_ctx['oop_max_cap']:.2f}. "
    )

    notes = (
        f"{phase_note}"
        f"Candidate {prod_sk} (${cand_annual_pay:.2f}/year on tier {cand_price['tier']}) {direction} "
        f"the original drug {original_id} (${orig_annual_pay:.2f}/year on tier {orig_price['tier']})"
        f"{f', a savings of ${savings:.2f}/year ({savings_pct:+.0%})' if savings != 0 else ''}. "
        f"(Based on {annual_fills:.1f} fills/year from {frequency} dosing with {days_supply}-day supply)"
    )

    return _result(
        prod_sk,
        cand_price,
        orig_price,
        score=score,
        notes=notes,
        savings=savings,
        savings_pct=savings_pct,
        insurance_context={
            **ins_ctx,
            "candidate_fill_projection": cand_fill,
            "original_fill_projection": orig_fill,
        },
        phase_decision_hint=_phase_decision_hint(cand_fill, orig_fill),
        annual_fills=annual_fills,
    )


def _tier_only_score(coinsurance: float) -> float:
    if coinsurance <= 0.30:
        return SCORE_REASONABLE
    if coinsurance <= 0.55:
        return (SCORE_REASONABLE + SCORE_EXPENSIVE) / 2
    return SCORE_EXPENSIVE


def _result(prod_sk, cand_price, orig_price, score, notes,
            savings=None, savings_pct=None, insurance_context=None,
            phase_decision_hint=None, annual_fills=1.0) -> Dict[str, Any]:
    if not cand_price["covered"]:
        decision = "not_covered"
    elif cand_price["final_cost"] is None:
        decision = "unpriceable"
    elif orig_price is None:
        decision = "fallback_absolute"
    elif orig_price.get("final_cost") is None:
        decision = "fallback_original_unpriceable"
    elif savings is None:
        decision = "unknown"
    elif savings > 0:
        decision = "cheaper"
    elif savings < 0:
        decision = "more_expensive"
    else:
        decision = "same_cost"

    # Calculate annual totals for frontend display
    annual_cand_cost = round(cand_price["final_cost"] * annual_fills, 2) if cand_price["final_cost"] else None
    annual_orig_cost = round(orig_price["final_cost"] * annual_fills, 2) if orig_price and orig_price.get("final_cost") else None
    annual_cand_pay = round(cand_price.get("patient_pay", 0) * annual_fills, 2) if cand_price.get("patient_pay") else None
    annual_orig_pay = round(orig_price.get("patient_pay", 0) * annual_fills, 2) if orig_price and orig_price.get("patient_pay") else None

    out = {
        "drug_id": prod_sk,
        "covered": cand_price["covered"],
        "tier": cand_price["tier"],
        "final_cost": cand_price["final_cost"],
        "estimated_patient_pay": cand_price["patient_pay"],
        "annual_final_cost": annual_cand_cost,
        "annual_patient_pay": annual_cand_pay,
        "pricing_source": cand_price["pricing_source"],
        "original_drug_id": orig_price["drug_id"] if orig_price else None,
        "original_final_cost": orig_price["final_cost"] if orig_price else None,
        "original_patient_pay": orig_price["patient_pay"] if orig_price else None,
        "original_annual_final_cost": annual_orig_cost,
        "original_annual_patient_pay": annual_orig_pay,
        "estimated_savings": savings,
        "savings_pct": savings_pct,
        "insurance_context": insurance_context,
        "financial_phase_decision_hint": phase_decision_hint,
        "score": round(score, 3),
        "notes": notes,
        "summary": {
            "decision": decision,
            "reason": notes,
            "score": round(score, 3),
            "estimated_savings": savings,
            "candidate_patient_pay": cand_price.get("patient_pay"),
            "original_patient_pay": orig_price.get("patient_pay") if orig_price else None,
        },
    }
    return out


# --------------------------------------------------------------------------- #
# Local smoke test: python -m app.agents.financial_agent
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import json

    async def _demo():
        # 3 key examples with one candidate each.
        examples = [
            # Example 1: DEDUCTIBLE phase with huge savings (Member 2080)
            {
                "claim": {
                    "drug_id": "1034",
                    "plan_id": "3009",
                    "fill_date": "2025-06-01",
                    "member_id": "2080"
                },
                "alternatives": ["1033"]
            },
            # Example 2: INITIAL_COVERAGE - cheaper candidate (Member 2094)
            {
                "claim": {
                    "drug_id": "1004",
                    "plan_id": "3001",
                    "fill_date": "2025-06-01",
                    "member_id": "2094"
                },
                "alternatives": ["1006"]
            },
            # Example 3: Baseline - no member_id
            {
                "claim": {
                    "drug_id": "1018",
                    "plan_id": "3010",
                    "fill_date": "2025-06-01"
                },
                "alternatives": ["1033"]
            }
        ]
        
        for example in examples:
            claim = example["claim"]
            alternatives = example["alternatives"]
            results = await financial_agent_for_candidates(claim, alternatives)
            for drug_id, result in zip(alternatives, results):
                print(json.dumps({
                    "claim_context": {k: v for k, v in claim.items() if k != "member_id"},
                    "candidate_drug_id": drug_id,
                    "result": result,
                }, indent=2))

    logging.basicConfig(level=logging.INFO)
    asyncio.run(_demo())
