# V2.6 Career Profile Matching

Validation date: 2026-08-30

## Scope

V2.6 adds a second semantic layer that answers how closely a job matches a target
career direction. It remains separate from semantic categories, which describe
what kind of role the job is.

The implementation is additive:

```text
Canonical Job
  -> Hard Filter
  -> Pre-Score
  -> Semantic Categories
  -> Career Profile Similarities
```

Career profiles do not reject jobs, change the pre-score, apply personal weights,
or use a similarity threshold. The existing LM Studio endpoint,
Qwen3-Embedding-0.6B model, 1024 dimensions, and 40/60 title-description weighting
are reused. Category and profile embedding statuses are stored separately.

## Profiles

`config/career_profiles.yaml` defines four independent directions:

- `automation_data`
- `technical_project_management`
- `process_consulting`
- `data_bi`

Each `ProfileMatch` stores combined, title, and optional description similarity.
Raw vectors are never attached to jobs, API results, fixtures, or cache data.

## Frozen Benchmark

`tests/fixtures/career_profiles.json` contains 24 authored cases:

| Group | Cases |
| --- | ---: |
| Automation and data | 4 |
| Technical project management | 4 |
| Process consulting | 4 |
| Data and BI | 4 |
| Multi-profile boundaries | 6 |
| No profile fit | 2 |

The 22 matched cases produced:

| Metric | Result |
| --- | ---: |
| Top-1 correct | 21 / 22 |
| Top-1 accuracy | 95.45% |
| Top-2 recalled | 22 / 22 |
| Top-2 recall | 100.00% |
| Mean best-primary rank | 1.045 |

Dataset SHA-256:
`6107c77cbc80a40645acaf04a355b412689852aec00ebaf6cdc2e3fbb8b46b30`.

The only Top-1 miss is `Data & Automation Consultant`: `data_bi` ranks first,
followed by the expected `process_consulting` and `automation_data` profiles. This
is a successful Top-2 result and a plausible three-way boundary rather than a
reason to change the profile descriptions immediately.

`acceptable_secondary` is preserved in the dataset and output but does not affect
Top-1 accuracy or Top-2 recall. Both metrics exclusively evaluate
`expected_primary`.

## Live Sample

The additional JobSpy run used five discovery queries, up to three results per
query, a 100 km Karlsruhe radius, and a 14-day age limit. It yielded 16 accepted
deduplicated jobs with no source failures.

| Measurement | Result |
| --- | ---: |
| Live jobs | 16 |
| Descriptions available | 8 |
| Category successes | 16 / 16 |
| Career-profile successes | 16 / 16 |

Top-profile distribution:

| Profile | Count |
| --- | ---: |
| process_consulting | 10 |
| technical_project_management | 3 |
| automation_data | 2 |
| data_bi | 1 |

Representative category/profile pairs:

| Job | Category top | Career-profile top |
| --- | --- | --- |
| AI & Automation Engineer | automation | automation_data |
| Network Automation Engineer | automation | automation_data |
| Manager Process Automatisation & Improvement | process_management | process_consulting |
| Business Process Expert / SAP OTC | process_management | process_consulting |
| Software Project Manager | project_management | technical_project_management |
| IT Projektmanager | project_management | technical_project_management |
| AIML Frontend Engineer | automation | data_bi |

The sample is intentionally influenced by its discovery queries and is too small
to infer production prevalence. `process_consulting` leads 10 of 16 jobs, including
some broad or opaque roles. This should be examined in V2.6.1 against additional
frozen real-world examples before any profile weighting or downstream scoring is
considered.

## Reproduction

Run the frozen benchmark:

```powershell
.venv\Scripts\python.exe scripts\evaluate_career_profiles.py
```

Run the compact benchmark and live validation:

```powershell
.venv\Scripts\python.exe scripts\evaluate_career_profiles.py --live --results-per-query 3 --limit 20 --summary-only
```

No threshold is introduced by this report. No profile similarity changes job
acceptance or the deterministic pre-score.

