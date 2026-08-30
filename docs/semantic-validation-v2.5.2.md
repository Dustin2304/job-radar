# V2.5.2 Category Calibration

Validation date: 2026-08-30

## Scope

V2.5.2 changed only the semantic descriptions of `automation`,
`process_management`, and `supply_chain` in `config/categories.yaml`. Python code,
the embedding model, the 40/60 weighting, pre-score behavior, and n8n integration
were unchanged.

The first proposed descriptions were deliberately verbose. A reference run showed
that this reduced the target similarities as well as the unwanted overlap:

- `Business Process Analyst`: process management fell from `0.755` to `0.689`.
- `Supply Chain Planner`: supply chain fell from `0.768` to `0.712`.

The same concepts were therefore retained in shorter, role-oriented descriptions.
The final live run used the unchanged V2.5.1 evaluator and command.

## Reference Titles

| Title | V2.5.1 top | V2.5.2 top categories | Result |
| --- | --- | --- | --- |
| Junior Automation Engineer | automation `0.740` | automation `0.746`, data `0.618`, consulting `0.606` | Stable and slightly stronger |
| Data Engineer | data `0.769` | data `0.769`, automation `0.670`, consulting `0.659` | Stable |
| Business Process Analyst | automation `0.770` | process_management `0.761`, business_intelligence `0.692`, consulting `0.674` | Target category is now first |
| Supply Chain Planner | supply_chain `0.768` | supply_chain `0.728`, automation `0.621`, project_management `0.600` | Stable first place with less automation overlap |
| IT Consultant Digital Transformation | consulting `0.782` | consulting `0.782`, project_management `0.633`, automation `0.615` | Stable first place with less automation overlap |

All five fixed references now have the expected category in first place.

## Live Comparison

JobSpy returned 28 accepted jobs in the final run, compared with 30 in V2.5.1.
Because this is a live search, individual listings and the number of returned jobs
can change between runs. Aggregate counts are therefore diagnostic rather than a
strict accuracy benchmark.

| Metric | V2.5.1 | V2.5.2 |
| --- | ---: | ---: |
| Accepted live jobs | 30 | 28 |
| Embedding successes | 30 | 28 |
| Source failures | 0 | 0 |
| Description available | 15 | 15 |
| Title only | 15 | 13 |
| Manually good or plausible top category | 21 | 22 |
| Questionable top category | 7 | 5 |
| Edge case without a clear category | 2 | 1 |

The good/plausible rate improved from `70.0%` to `78.6%`. This does not yet reach
the aspirational 25/30 rate, but the category distribution is substantially less
biased and the remaining errors are more localized.

Combined top-category distribution:

| Category | V2.5.1 | V2.5.2 |
| --- | ---: | ---: |
| automation | 19 | 10 |
| supply_chain | 4 | 5 |
| consulting | 3 | 5 |
| data | 3 | 2 |
| business_intelligence | 1 | 2 |
| process_management | 0 | 2 |
| project_management | 0 | 1 |

## Regression Cases

| Case | V2.5.1 | V2.5.2 | Assessment |
| --- | --- | --- | --- |
| Business Process Analyst reference | automation #1, process #2 | process #1 | Fixed |
| Business Process Consultant | automation #1 | consulting #1, process #2, automation #3 | Fixed in an intermediate run; listing was absent from the final live sample |
| Business Analyst Workflowmanagementsystem | automation #1, process #3 | BI #1, process #2, automation #3 | Process moved clearly above automation in an intermediate run; listing was absent from the final sample |
| Digital Procurement Analyst | automation #1 | consulting #1, project #2, automation #3 | Automation bias fixed, but supply chain is still missing from the top three |
| Planner Produktportfolio, Demand & Supply | automation #1 | supply_chain #1 | Fixed |
| Business Process Expert Quality Management | not sampled | process_management #1 | New positive process-management case |
| Business Process Expert / SAP OTC | not sampled | process_management #1 | New positive process-management case |

Clear successes remained stable: AI & Automation Engineer, HR process automation,
automation engineering, Network Automation Engineer, explicit data-engineering
roles, planning and supply-chain roles, and digital-transformation consulting all
kept a sensible dominant category.

Remaining questionable cases include AI & Automation Specialist, UiPath Business
Analyst, the AIML frontend role, Digital Procurement Analyst, and Order Management
Specialist. Field Operations Associate remains an edge case without a clearly
matching taxonomy category.

## Decision

The calibration is a material improvement and confirms that category wording can
correct the broad automation bias without changing the model or weights. It should
be kept as V2.5.2.

Further ad-hoc wording changes would be difficult to evaluate reliably against a
changing live sample. The next useful step is a small persisted semantic regression
dataset with expected primary and acceptable secondary categories, followed by
Top-1 accuracy and Top-2 recall measurements. No weighting or model change is
justified by this run.

## Reproduction

With LM Studio running on `127.0.0.1:1234` and the configured model loaded:

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_categories.py --live --results-per-query 5 --limit 30
```

