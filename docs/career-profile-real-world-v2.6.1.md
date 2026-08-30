# V2.6.1 Real-World Career Profile Benchmark

Validation date: 2026-08-30

## Scope

V2.6.1 validates the four career profiles against frozen real job data before any
profile wording is changed. It adds confusion analysis and Top-1/Top-2 similarity
margins but introduces no thresholds, gates, preference weights, pre-score changes,
n8n changes, or LLM changes.

The existing 24-case synthetic fixture remains unchanged.

## Local Snapshot

The capture utility queried 22 deliberately varied search terms around Karlsruhe,
covering the four target directions, multi-profile boundaries, and eight kinds of
potential no-fit roles. It captured 40 accepted jobs without source failures.

Five duplicate or near-duplicate postings were removed during manual review. The
final ignored dataset under `data/evaluation/` contains:

| Measurement | Count |
| --- | ---: |
| Frozen real jobs | 35 |
| Description available | 25 |
| Title only | 10 |
| Profile-labelled cases | 16 |
| No-fit cases | 19 |
| Multi-primary cases | 5 |
| Single-primary cases | 11 |

The complete descriptions and manual label map remain local and are excluded by
Git. No real description is committed. The labelled local dataset SHA-256 is
`836950b2ca7008d48d30578b79830f2135d9e0555112ce3d3752813788c0fc03`.

Manual labels were assigned from title and description before the classifier
results were inspected. Discovery queries were retained as provenance but were not
used as labels.

## Variant A: Current Profiles

Variant A is the committed `config/career_profiles.yaml`, SHA-256
`1212c5cf01c8bd061e93afc0690e86d7967928193ba4871b1c0ff551669e0dda`.

| Metric | Result |
| --- | ---: |
| Top-1 correct | 16 / 16 |
| Top-1 accuracy | 100.00% |
| Top-2 recalled | 16 / 16 |
| Top-2 recall | 100.00% |
| Mean best-primary rank | 1.000 |

The confusion matrix intentionally includes only the 11 unambiguous
single-primary cases. Multi-primary cases are evaluated by Top-1/Top-2 metrics but
are excluded from confusion rows.

| Expected | automation_data | technical_project_management | process_consulting | data_bi |
| --- | ---: | ---: | ---: | ---: |
| automation_data | 4 | 0 | 0 | 0 |
| technical_project_management | 0 | 3 | 0 | 0 |
| process_consulting | 0 | 0 | 2 | 0 |
| data_bi | 0 | 0 | 0 | 2 |

### Similarity Margins

`Top-1 margin` is the combined similarity of rank one minus rank two. It is an
observation only and does not affect job acceptance.

| Case type | Mean | Median | Min | Max |
| --- | ---: | ---: | ---: | ---: |
| All matched | 0.0634 | 0.0474 | 0.0044 | 0.1868 |
| Single-primary | 0.0481 | 0.0451 | 0.0044 | 0.1371 |
| Multi-primary | 0.0970 | 0.1125 | 0.0236 | 0.1868 |

The small minimum margins confirm that correct Top-1 results can still be genuine
semantic boundary cases. Margin must not be treated as confidence without further
calibration.

### No-Fit Observations

All 19 no-fit jobs still receive a strongest profile because there is no threshold.
They remain excluded from accuracy, recall, and confusion metrics.

| Top profile | Count |
| --- | ---: |
| data_bi | 8 |
| process_consulting | 6 |
| technical_project_management | 4 |
| automation_data | 1 |

Their mean Top-1 similarity is `0.4649` with median `0.4523`. Their mean Top-1
margin is only `0.0143` with median `0.0083`, substantially below the matched-case
margin. The sample is still insufficient to introduce a threshold.

## Variant B: Seniority Terms Removed

Variant B removes only `Junior` and `early-career` wording while retaining the same
four profile names and technical concepts. It remains local under
`data/evaluation/`; SHA-256
`73caf3096b0a1092ab97d5626cb4922619b4ed046843ece32353540fcdf840ce`.

| Metric | Variant A | Variant B |
| --- | ---: | ---: |
| Top-1 accuracy | 100.00% | 75.00% |
| Top-2 recall | 100.00% | 93.75% |
| Mean best-primary rank | 1.000 | 1.313 |
| Mean matched margin | 0.0634 | 0.0586 |

Variant B produced four Top-1 regressions:

- Engineer - Technical Scaling & Emerging Technologies: expected
  `automation_data`, ranked second behind `technical_project_management`.
- Local Service Unit Quality & CI Manager: expected `process_consulting`, ranked
  second behind `technical_project_management`.
- Engineering Productivity Innovator: expected `automation_data` or
  `process_consulting`, ranked second behind `technical_project_management`.
- Operations Performance Specialist: expected `process_consulting`, ranked third
  behind `technical_project_management` and `data_bi`.

Variant B also raised the no-fit mean Top-1 similarity from `0.4649` to `0.4895`
and more than doubled its mean margin from `0.0143` to `0.0277`. Removing the
seniority wording therefore made the tested profile space less accurate and more
confident on unrelated roles.

## Decision

Keep Variant A unchanged. Variant B is materially worse on the frozen real-world
benchmark and does not justify modifying the committed profile descriptions.

This result does not prove that seniority belongs permanently inside career
profiles. It shows only that this exact shorter formulation moves the embedding
centres in an undesirable direction. Seniority remains independently represented
in the deterministic pre-score, and no profile similarity affects that component.

## Reproduction

Capture a new ignored draft snapshot:

```powershell
.venv\Scripts\python.exe scripts\capture_career_profile_snapshot.py
```

Apply a local manual label map:

```powershell
.venv\Scripts\python.exe scripts\label_career_profile_snapshot.py
```

Run the local A/B comparison:

```powershell
.venv\Scripts\python.exe scripts\evaluate_career_profiles.py `
  --dataset data\evaluation\career-profile-real-world-labelled.json `
  --compare-profiles data\evaluation\career_profiles_no_seniority.yaml `
  --summary-only
```

`acceptable_secondary` is reported but does not rescue Top-1 or Top-2 metrics;
those continue to use only `expected_primary`.
