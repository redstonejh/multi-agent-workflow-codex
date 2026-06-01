# ML Validation — Specialized Checks, Validators & Rubric

A generic `critic` agent is not enough for ML work. "The metric went up" is exactly the kind of result most likely to be an artifact. This doc catalogs the ways ML results mislead, the concrete check for each, and how they become **specialized validator agents + tools + a quality rubric** inside the framework.

Guiding principle: **many of these checks are programmatic, not LLM judgment.** Computing a train–test gap, running a shuffled-label control, or measuring calibration are `@tool`s the validator agents call. The agent's job is to *orchestrate the checks and interpret them*, not to eyeball a number. The quality bar for an ML workflow is therefore "passes the audits," not "the critic likes it."

---

## The failure modes & their checks

### 1. Overfitting (poor generalization)
Model memorizes training data instead of learning generalizable structure.
- **Train-vs-held-out gap** — large gap between train and validation/test score is the classic tell; track both.
- **Learning curves** — performance vs. training-set size and vs. epochs; overfit models keep improving on train while val plateaus/degrades.
- **K-fold cross-validation stability** — wild swings across folds mean a fragile result.
- **Held-out test set used exactly once** — tuning against it destroys it as a test.
- **Regularization / early-stopping controls** — if removing them collapses the gap, you were overfitting.

### 2. Data leakage (inflates *every* metric — the most dangerous)
Information unavailable at prediction time leaks into training.
- **Target leakage** — a feature encoding the label or the future; audit each feature: would this value exist *before* the prediction moment?
- **Preprocessing leakage** — scalers/imputers/feature-selection fit on the full dataset; all preprocessing must be fit on train only, inside each CV fold.
- **Temporal leakage** — random splits on time-ordered data; use time-based splits.
- **Group/entity leakage** — same patient/user/device in train and test; use grouped splits.
- **Duplicate / near-duplicate rows** spanning the split.
- **Shuffled-label sanity check** — randomize labels and retrain; above-chance performance ⇒ leakage or a bug. Catches a shocking amount.

### 3. Validation & evaluation design
- **Tuning on the test set / no held-out test.**
- **Hyperparameter (multiple-comparisons) overfitting** — try enough configs and one looks great by chance; validate the winner on fresh data.
- **Benchmark/test-set reuse over time** slowly leaks it.

### 4. Misleading metrics
- **Accuracy on imbalanced data** — 99% accuracy at 99% base rate is worthless; use precision/recall, F1, PR-AUC, balanced accuracy.
- **Wrong metric for the goal** — ranking (AUC) vs. rare-event detection (PR-AUC) vs. probability quality (calibration).
- **Threshold games** — metrics reported at a cherry-picked decision threshold.
- **Aggregate masking subgroups** — strong overall, poor on a slice that matters.

### 5. Baselines & statistical significance
- **No naive baseline** — always compare to majority-class / simple heuristic / last-value; many "good" models barely beat trivial ones.
- **No variance reporting** — a single run is noise; run multiple seeds, report mean ± std / CIs. An improvement smaller than seed-to-seed variance isn't one.
- **No significance test** on the model-vs-baseline gap.

### 6. Generalization & robustness
- **Distribution shift / train-serving skew** — eval data doesn't match deployment; check covariate shift; for time series test the most recent period.
- **Shortcut learning / spurious correlations** — model latches onto artifacts (background, scanner ID, watermark); inspect suspiciously strong features; test perturbed/counterfactual inputs.
- **Calibration** — predicted probabilities should match observed frequencies (reliability diagram, ECE); a model can rank well yet report nonsense probabilities.

### 7. Data & objective integrity
- **Label noise / quality** — mislabeled ground truth caps and distorts results; check inter-annotator agreement, audit a sample.
- **Sampling / selection bias** in data collection.
- **Proxy / Goodhart mismatch** — optimizing a metric that diverges from the real objective.
- **Causal overclaiming** — reading feature importance from a correlational model as causal.

### 8. Reproducibility
- Fixed seeds, pinned environment, versioned data. A result that can't be reproduced isn't one.

---

## Validator agents (the ML roster)

Instead of one `critic`, the ML roster registers specialized validators. The conductor pulls in whichever the task warrants. Each combines tool-computed evidence with agent interpretation.

| Validator agent | Owns | Backed by tools |
|---|---|---|
| `leakage_auditor` | target/temporal/group/preprocessing leakage, shuffled-label control | feature-time audit, duplicate finder, shuffle-label retrain |
| `overfitting_checker` | train-test gap, learning curves, CV stability | gap calc, CV runner, learning-curve generator |
| `metric_validator` | right metric for the goal, imbalance handling, threshold sanity | metric suite (PR-AUC, F1, balanced acc), class-balance report |
| `baseline_enforcer` | naive baselines, significance of the gain | baseline trainer, bootstrap/permutation significance test |
| `variance_auditor` | multi-seed stability, confidence intervals | multi-seed runner, CI computation |
| `robustness_tester` | distribution shift, shortcut learning, perturbation tests | drift detector, perturbation harness, feature-importance probe |
| `calibration_checker` | probability calibration | reliability diagram, ECE |
| `data_quality_auditor` | label noise, sampling bias | label-audit sampler, class/subgroup distribution report |
| `reproducibility_checker` | seeds, env, data versioning | env/seed/data-hash capture |

## Tool-computed vs. agent-judged

Split each check so the framework relies on computation where it can:

- **Tool-computed (deterministic, trustworthy):** train-test gap, CV variance, learning curves, shuffled-label control, duplicate detection, metric suite, class balance, baseline performance, significance tests, multi-seed variance, ECE/calibration, drift statistics, data hashes.
- **Agent-judged (interpretation / reasoning):** is *this specific feature* plausibly future information? is the chosen metric appropriate for the stated goal? does the perturbation result indicate a shortcut? is the baseline a fair one? are subgroup gaps acceptable for the use case?

The validator agent runs its tools, reads the numbers, and renders a verdict with justification — number first, judgment second.

## The ML evaluation rubric (what `refine` enforces)

For an ML workflow, the evaluator's structured output isn't a vibe score — it's a checklist with hard gates. Example rubric the `refine` loop scores against:

```
PASS requires ALL of:
  [ ] leakage:        shuffled-label control at chance; no future/group leakage found
  [ ] overfitting:    train-test gap within tolerance; CV std below threshold
  [ ] baseline:       beats naive baseline by > seed-to-seed variance
  [ ] significance:   improvement statistically significant (p < 0.05 or CI excludes baseline)
  [ ] metric:         metric appropriate for goal; reported on imbalanced-aware terms
  [ ] robustness:     no dominant spurious feature; acceptable on recent/held-out period
  [ ] calibration:    ECE below threshold (if probabilities are used)
  [ ] reproducible:   seed/env/data version captured

SCORE = primary metric, reported only if all gates PASS; otherwise FAIL + critique.
```

The critique that comes back to the generator is specific ("shuffled-label control scored 0.74 — investigate `last_login_after_churn`, likely target leakage"), so the next iteration is targeted rather than guesswork.

## Two tiers: component validators vs. the acceptance gate

The validators above are **component checks** — each verifies one aspect of the *modeling process*. They are necessary but not sufficient: a model can pass every one and the *delivered result* can still be wrong or misrepresented. So ML runs end with the framework's terminal **acceptance gate** (core concept in `01-architecture.md`), specialized for ML. It is independent (a different agent/model than produced the work) and runs once, last.

What the ML acceptance gate adds beyond the component validators:

- **Task conformance** — does the model serve the *actual objective*, not just the metric? (e.g. a churn model that only flags customers after they've effectively left passes AUC but fails the retention goal.) Agent-judged against the original request.
- **Claim-to-evidence audit** — re-reads `memory.md` + every validator finding + artifacts, and confirms the final report/summary states nothing the evidence doesn't support: no inflated metric, no dropped failed gate, no "generalizes well" when `variance_auditor` flagged instability. Tool-assisted (parse the recorded numbers) + agent-judged (does the prose match).
- **End-to-end smoke test** — runs the *assembled pipeline* on genuinely fresh/synthetic input and checks the output is sane (valid ranges, no NaNs, plausible distribution, latency within bounds). Catches integration breakage and train-serving skew the held-out splits never exercise.

### Acceptance-gate agent + tools

```python
@tool
def claim_evidence_audit(report_md: str, run_dir: str) -> dict:
    """Cross-check each quantitative claim in the report against recorded
    values in the run folder; return unsupported/contradicted claims."""
    return cross_check_claims(report_md, run_dir)

@tool
def pipeline_smoke_test(pipeline_ref: str, fresh_input: str) -> dict:
    """Run the full pipeline on new input; report range/NaN/distribution sanity."""
    return run_and_check(pipeline_ref, fresh_input)

@agent(model="claude-opus-4-6",                 # different model/seed than producers
       tools=[claim_evidence_audit, pipeline_smoke_test],
       output_schema=Acceptance)                 # {ship: bool, reasons: [...], needs_human: bool}
def acceptance_gate():
    """You did NOT build this model. Independently decide if the deliverable ships:
    (1) does it answer the original request and objective; (2) does every claim in
    the output trace to evidence in the run folder; (3) does it run sanely end-to-end.
    Return SHIP / NO-SHIP with specific reasons. Flag for human sign-off if high-stakes
    or uncertain."""
```

This is deliberately separate from the per-component evaluator used inside `refine`: the evaluator improves the work; the acceptance gate, run once at the very end by an independent agent, decides whether the finished deliverable is fit to ship — and is bounded (the last automated check, with a human-sign-off escape hatch rather than infinite re-verification).

## How it runs end-to-end

```
conductor ─▶ plan team: [planner, ml_engineer×N, leakage_auditor,
                         overfitting_checker, baseline_enforcer, variance_auditor]
   │
   ├─ ml_engineer runs experiments (tools: training, eval)
   ├─ validators run their tool-backed checks, write findings to memory.md
   ├─ refine loop: evaluator applies the rubric → PASS/FAIL + critique
   ├─ loops (escalating: more seeds, fix leakage, stronger baseline) until all gates PASS
   └─ ACCEPTANCE GATE (independent agent, once): task conformance +
        claim-to-evidence audit + end-to-end smoke test → SHIP / NO-SHIP
        (NO-SHIP loops back with reasons; high-stakes/uncertain → human sign-off)
```

So the framework can't be fooled by a single shiny number — a result only counts as "good" once it survives the component audits, *and* an independent gate confirms the finished deliverable answers the real ask, reports honestly, and runs end-to-end. The run folder contains the markdown evidence for every gate.
