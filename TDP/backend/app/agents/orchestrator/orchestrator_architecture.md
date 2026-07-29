# Orchestrator Workflow — Weighted Score + Borda Consensus

## 1. Pipeline Overview

```text
Pharmacist Input → Clinical Agent → Filtered Alternatives
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              Policy Agent        Financial Agent      Past Decision Agent
                    └────────────────────┼────────────────────┘
                                         ▼
                          Per-Agent Scores + Rankings
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                                          ▼
                 Weighted Score Fusion               Weighted Borda Consensus
                 (magnitude-aware)                     (consensus-aware)
                    └────────────────────┬────────────────────┘
                                         ▼
                              Aggregate Score
                                         │
                                         ▼
                              Risk Adjustment
                                         │
                                         ▼
                              Final Ranking + Decision Band
                                         │
                               LLM Ranking Review Gate
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                        Auto Accept           Provider Review
                              ▼                     │
                             PBM ◄──────────────────┘
```

---

## 2. Layer-by-Layer Procedure

### Layer 1 — Agent Calls

Call the following agents on all surviving alternatives:

- Policy Agent
- Financial Agent
- Past Decision Agent

Each returns:

```json
{
  "score": 0-1,
  "reasoning": "..."
}
```

---

### Layer 2 — Hard Rules




```

Escalate immediately when:


```text
policy_state = pending
(PA required
step therapy required
quantity limits)
missing clinical data
```

---

### Layer 3 — Static Agent Weights

Weights remain fixed and version-controlled.

```text
Policy Agent         = 0.35
Financial Agent      = 0.30
Past Decision Agent  = 0.35
```

```text
Σ weights = 1.00
```

No case-specific logic modifies agent weighting.

---

### Layer 4a — Weighted Score Fusion

Preserve magnitude information from agent scores.

```text
ScoreFusion(alt)
=
Σ(
Weightagent × Scoreagent(alt)
)
```

Example:

```text
ScoreFusion
=
(0.35 × PolicyScore)
+
(0.30 × FinancialScore)
+
(0.35 × PastDecisionScore)
```

This captures the strength of each recommendation.

---

### Layer 4b — Weighted Borda Consensus

Capture cross-agent agreement using Borda Count.

For N surviving alternatives:

```text
Rank 1 = N points
Rank 2 = N − 1 points
...
Rank N = 1 point
```

For each alternative:

```text
BordaScore(alt)
=
Σ(
Weightagent × BordaPointsagent(alt)
)
```

#### Normalize Borda Scores

```text
BordaNorm(alt)
=
(BordaScore(alt) - MinBorda)
/
(MaxBorda - MinBorda)
```

If:

```text
MaxBorda = MinBorda
```

then:

```text
BordaNorm = 1
```

for all alternatives.

#### Purpose

Weighted Borda rewards alternatives that are consistently preferred across multiple agents, even when they are not the top recommendation from every agent.

---

### Layer 4c — Aggregate Score

Combine magnitude and consensus.

```text
AggregateScore(alt)
=
0.70 × ScoreFusion(alt)
+
0.30 × BordaNorm(alt)
```

Rationale:

- Score Fusion captures recommendation strength.
- Borda captures cross-agent consensus.
- Magnitude remains the primary driver.
- Consensus acts as a stabilizing influence.

---

### Layer 5 — Risk Adjustment

```text
AdjustedScore(alt)
=
AggregateScore(alt)
− Σ(applicable penalties)
```

| Flag | Penalty |
|--------|---------|
| Clinical ambiguity | -0.05 |
| Cumulative risk | -0.05 |
| Polypharmacy | -0.03 |

---

### Layer 6 — Final Ranking & Decision Band

Rank alternatives:

```text
Sort by AdjustedScore descending
```

#### Final Tie Resolution

If alternatives remain tied after risk adjustment:

```text
1. Higher Clinical Agent composite score
2. Higher Policy Agent score
3. Lower projected total cost
4. Higher historical approval rate
5. Provider Review required
```

#### Decision Bands

| Band | Range | Decision |
|--------|---------|---------|
| 1 | ≥ 0.80 | Auto Accept (provisional) |
| 2 | 0.50 - 0.79 | Provider Review |
| 3 | < 0.50 | Dispense as Written |

---

### Layer 7 — LLM Ranking Review Gate (Unconditional, Downgrade-Only)

Runs on every case.

Input:

- Final ranking
- Top alternative rationales
- Consensus signals
- Cross-agent disagreement indicators

Output:

```json
{
  "agrees_with_ranking": true,
  "suggested_reorder": null,
  "reasoning_conflict_detected": false,
  "unaddressed_safety_language": false,
  "recommended_action": "auto_approve",
  "note": "<=40 words"
}
```

Decision logic:

```text
IF Band = Auto Accept
AND all LLM checks pass
AND recommended_action = auto_approve

→ Remain Auto Accept

ELSE

→ Downgrade to Provider Review
```

Fail-safe:

```text
LLM timeout
LLM schema failure
LLM processing error

→ Provider Review
```

The LLM can only downgrade.

It can never upgrade a recommendation.

---

### Layer 8 — Summary Generation

Generate final audit-ready summary including:

- Ranked alternatives
- Agent scores
- Borda consensus contribution
- Risk adjustments
- Final decision
- Review notes

---

## 3. Final Orchestrator Algorithm

```text
1. Receive alternatives from Clinical Agent
2. Call Policy / Financial / Past Decision agents
3. Evaluate hard rules and escalate if violated
4. Load static agent weights
5. Compute Weighted Score Fusion
6. Compute Weighted Borda Consensus
7. Compute Aggregate Score
8. Apply risk penalties
9. Produce final ranking
10. Assign decision band
11. Execute LLM Review Gate
12. Generate summary
13. Send decision to PBM or Provider
```

---

## 4. Configurable Constants

| Constant | Default | Notes |
|-----------|-----------|---------|
| Agent Weights | Policy .35 / Financial .30 / Past .35 | Sum = 1.0 |
| Score Fusion : Borda Blend | 70 / 30 | Magnitude prioritized over consensus |
| Clinical Ambiguity Penalty | -0.05 | Per occurrence |
| Cumulative Risk Penalty | -0.05 | Per occurrence |
| Polypharmacy Penalty | -0.03 | Per occurrence |
| Decision Bands | ≥0.80 / 0.50-0.79 / <0.50 | Version controlled |
