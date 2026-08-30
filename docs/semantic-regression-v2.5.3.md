# V2.5.3 Semantic Regression Benchmark

Validation date: 2026-08-30

## Purpose

V2.5.3 replaces comparisons between changing live samples with a small persisted,
manually labelled benchmark. It measures category-ranking changes without adding a
similarity threshold or changing category descriptions, the embedding model, the
40/60 weighting, pre-score behavior, or n8n.

## Dataset

`tests/fixtures/semantic_categories.json` contains 30 deliberately selected cases:

| Group | Cases |
| --- | ---: |
| Automation | 4 |
| Data / BI | 4 |
| Process management | 4 |
| Supply chain | 4 |
| Consulting | 3 |
| Project management | 3 |
| Multi-category boundaries | 5 |
| No taxonomy fit | 3 |

The committed cases contain job titles and short, original semantic summaries.
They do not contain copied job descriptions. Five boundary cases allow multiple
primary categories. `acceptable_secondary` preserves useful secondary signals but
does not make an incorrect Top-1 result correct.

Cases with `taxonomy_fit: none` intentionally have no expected category. They are
reported separately and excluded from Top-1 accuracy, Top-2 recall, and mean rank;
without a calibrated threshold there is no principled pass/fail rule for them.

Private snapshots with real descriptions can use the same schema and be stored
under `data/evaluation/`, which is ignored by Git. Such a dataset can use the
optional `description` field instead of `semantic_summary`.

## Metrics

- **Top-1 accuracy:** the highest ranked category is in `expected_primary`.
- **Top-2 recall:** at least one expected primary category occurs in the first two.
- **Mean best-primary rank:** the average position of the highest-ranked expected
  primary category.

## Baseline

The first run used Qwen3-Embedding-0.6B with 1024 dimensions and the unchanged
40% title / 60% description weighting.

| Metric | Result |
| --- | ---: |
| Total cases | 30 |
| Labelled taxonomy matches | 27 |
| No-fit observations | 3 |
| Top-1 correct | 25 / 27 |
| Top-1 accuracy | 92.59% |
| Top-2 recalled | 26 / 27 |
| Top-2 recall | 96.30% |
| Mean best-primary rank | 1.259 |

The dataset SHA-256 for this baseline is
`11f29f29e0e9b03c6cd544fe54ec633e6fed69dd2291d67ffa7cef094b855eab`.

Two cases did not have an expected category at rank one:

| Case | Top categories | Best expected rank | Interpretation |
| --- | --- | ---: | --- |
| Digital Procurement Analyst | consulting, business_intelligence, automation | 7 | Supply-chain semantics are not captured by the current embedding/category combination |
| Order Management Specialist - Process Optimization | automation, process_management, consulting | 2 | Top-1 miss but successful Top-2 retrieval |

The three no-fit cases produced top similarities between `0.593` and `0.634`.
This is observational only: the sample is too small to establish a confidence or
rejection threshold.

## Reproduction

With the configured embedding model loaded in LM Studio:

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_regression.py
```

To evaluate a private frozen snapshot:

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_regression.py --dataset data/evaluation/semantic-live-snapshot.json
```

The evaluator prints the dataset hash, configuration, aggregate metrics, explicit
Top-1 regressions, and the Top-3 ranking for every case. It does not persist vectors.

## Decision

V2.5 now has a reproducible baseline. Future changes to category descriptions,
models, or weighting should report their metric delta against this fixture instead
of relying on a new live sample. The seven categories remain observational signals
and do not gate job acceptance.

