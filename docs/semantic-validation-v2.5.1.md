# V2.5.1 Semantic Validation

Validation date: 2026-08-30

## Setup

- LM Studio: `0.4.23+1`
- Model: Qwen3-Embedding-0.6B Q8_0 GGUF
- Actual API model ID: `text-embedding-qwen3-embedding-0.6b`
- Dimensions: `1024`
- Weighting: `40%` title, `60%` description
- Category descriptions: English
- Similarity threshold: none

The model was downloaded from the official Qwen GGUF repository, loaded through LM Studio, and accessed through `POST /v1/embeddings`. `GET /v1/models` confirmed the configured model ID. The technical smoke test produced 1024-dimensional vectors and `embedding_status=success`.

## Reference Titles

Reference validation intentionally used titles without descriptions. Rankings matter here; the absolute similarities are not percentages.

| Title | Top categories | Assessment |
| --- | --- | --- |
| Junior Automation Engineer | automation `0.740`, data `0.618`, consulting `0.606` | Expected category is first |
| Data Engineer | data `0.769`, automation `0.725`, consulting `0.659` | Expected category is first |
| Business Process Analyst | automation `0.770`, process_management `0.755`, business_intelligence `0.692` | Expected category is present but narrowly second |
| Supply Chain Planner | supply_chain `0.768`, automation `0.692`, project_management `0.600` | Expected category is first |
| IT Consultant Digital Transformation | consulting `0.782`, automation `0.711`, process_management `0.672` | Consulting is first and process management is present |

Four references have the expected dominant category. The process analyst exposes the main overlap: the current automation description is slightly stronger than process management even without explicit automation in the title.

## Live Sample

The live sample used five discovery queries around Karlsruhe with a 100 km radius and a 14-day age limit:

- `process automation`
- `data engineer`
- `business process analyst`
- `supply chain planner`
- `IT consultant digital transformation`

Indeed and LinkedIn were queried through JobSpy with normal LinkedIn search behavior and no detail enrichment. Jobs were deduplicated by canonical ID, URL, and normalized title/company, then passed through the existing hard filter. The sample contains 30 accepted jobs and had no source failures.

Legend: `T/D/C` means title, description, and combined similarity for the combined top category. `—` means that no description was available.

| # | Job | Input | Pre | Title top | Description top | Combined top T/D/C | Second combined | Manual assessment |
| ---: | --- | --- | ---: | --- | --- | --- | --- | --- |
| 1 | AI & Automation Specialist — Bilfinger NL | T+D | 72 | automation | consulting | automation `.770/.715/.737` | consulting `.721` | Good; consulting is a useful secondary signal |
| 2 | Engineering Productivity Innovator — Schwarz Corporate Solutions | T+D | 42 | automation | automation | automation `.648/.704/.681` | consulting `.627` | Plausible, but broad title |
| 3 | Engineering Productivity Innovator — Schwarz Digits | T+D | 42 | automation | automation | automation `.648/.695/.676` | consulting `.623` | Plausible, but broad title |
| 4 | Field Operations Associate — Circus | T+D | 40 | automation | automation | automation `.611/.637/.627` | project_management `.548` | Edge case without a clearly fitting category |
| 5 | UiPath Business Analyst — MHP | title | 22 | automation | — | automation `.765/—/.765` | business_intelligence `.710` | Good |
| 6 | AI & Automation Engineer — DAW | title | 28 | automation | — | automation `.762/—/.762` | consulting `.671` | Good |
| 7 | Spezialist HR-Prozessautomatisierung — dm | title | 27 | automation | — | automation `.756/—/.756` | consulting `.668` | Good; process management remains only third |
| 8 | Engineer Automatisierung — Etteplan | title | 28 | automation | — | automation `.762/—/.762` | consulting `.668` | Good |
| 9 | Engineering Productivity Innovator — Schwarz Corporate Solutions | T+D | 39 | automation | automation | automation `.645/.688/.671` | consulting `.633` | Plausible, but broad title |
| 10 | Engineering Productivity Innovator — Schwarz Digits | T+D | 39 | automation | automation | automation `.645/.691/.673` | consulting `.630` | Plausible, but broad title |
| 11 | AIML Frontend Engineer, Annotation Platform — Apple | T+D | 35 | automation | automation | automation `.674/.624/.644` | data `.573` | Questionable; software/data semantics are stronger than the category result suggests |
| 12 | Snowflake Data Engineer — adesso | title | 28 | data | — | data `.754/—/.754` | automation `.668` | Good |
| 13 | Data Engineer — Booz Allen Hamilton | title | 28 | data | — | data `.769/—/.769` | automation `.725` | Good |
| 14 | Data Engineer – Customer — BAUHAUS | title | 28 | data | — | data `.718/—/.718` | automation `.665` | Good |
| 15 | Data Engineer – Business Intelligence — GMX/WEB.DE | title | 46 | business_intelligence | — | business_intelligence `.746/—/.746` | data `.732` | Good multi-category ordering |
| 16 | ASI Manager — Leidos | T+D | 22 | automation | project_management | automation `.637/.597/.613` | project_management `.602` | Opaque edge case; description indicates project management |
| 17 | Revenue Operations Manager — TOPdesk | T+D | 40 | automation | business_intelligence | automation `.667/.666/.666` | business_intelligence `.661` | Questionable; BI/process should probably lead |
| 18 | Digital Procurement Analyst — Andritz | T+D | 31 | automation | automation | automation `.668/.675/.672` | consulting `.665` | Questionable; supply/process semantics are missing from the top results |
| 19 | Continuous Improvement Specialist — ABB | title | 22 | automation | — | automation `.649/—/.649` | process_management `.620` | Questionable; process management should lead |
| 20 | Business Analyst Workflowmanagementsystem — adesso | title | 22 | automation | — | automation `.731/—/.731` | business_intelligence `.697` | Questionable; process management is only third |
| 21 | Business Process Consultant — RÖDL | title | 28 | automation | — | automation `.747/—/.747` | consulting `.720` | Questionable; consulting/process should lead |
| 22 | IT-Business-Analyst — HELU KABEL | title | 22 | consulting | — | consulting `.702/—/.702` | automation `.681` | Plausible; process semantics remain weak |
| 23 | Planning & Fulfillment Specialist — ABB | T+D | 41 | automation | supply_chain | supply_chain `.678/.714/.700` | automation `.624` | Good; description corrects the ambiguous title |
| 24 | Production Planner — Capri Sun | T+D | 25 | supply_chain | supply_chain | supply_chain `.659/.620/.636` | automation `.591` | Good |
| 25 | Supply Chain Planner — DEINZER + WEYLAND | T+D | 28 | supply_chain | supply_chain | supply_chain `.749/.713/.727` | automation `.651` | Good |
| 26 | Planner Produktportfolio, Demand & Supply — Lactalis | title | 22 | automation | — | automation `.652/—/.652` | supply_chain `.645` | Questionable but close; supply chain should lead |
| 27 | Supply Chain Planner Service Parts — Heidelberger Druckmaschinen | title | 28 | supply_chain | — | supply_chain `.672/—/.672` | automation `.653` | Good |
| 28 | Network Automation Engineer — Hubert Burda Media | T+D | 41 | automation | automation | automation `.732/.696/.711` | consulting `.654` | Good |
| 29 | Consultant AI & Digital Transformation — P3 | T+D | 37 | consulting | consulting | consulting `.730/.711/.719` | automation `.660` | Good |
| 30 | Berater Digitale Transformation & IT-Strategie — EY | title | 22 | consulting | — | consulting `.772/—/.772` | automation `.697` | Good |

## Aggregate Observations

- Embedding success: `30/30`
- Description available: `15/30`
- Title only: `15/30`
- Manually good or plausible top category: `21/30`
- Questionable top category: `7/30`
- No clearly fitting category / opaque edge case: `2/30`
- Combined top category equals title top category: `29/30`
- Title and description disagree on top category: `4/15` description-backed jobs
- The description changed the final combined winner: `1/15` description-backed jobs

Combined top-category distribution:

| Category | Count |
| --- | ---: |
| automation | 19 |
| supply_chain | 4 |
| data | 3 |
| consulting | 3 |
| business_intelligence | 1 |
| process_management | 0 |
| project_management | 0 |

The discovery sample is intentionally category-biased, so these counts are not production prevalence. They are still diagnostically useful: process-oriented titles repeatedly rank automation first, and no sampled job ranks process management first.

## Decision

The result corresponds to validation outcome **C: the model is useful, but specific category descriptions overlap poorly**.

Qwen3-Embedding-0.6B is a viable first model. It handled German and English titles, identified explicit data, BI, supply-chain, consulting, and automation roles, and used descriptions to correct an ambiguous planning title. There is no evidence yet that another model is required.

The current `40/60` weighting is not the first calibration target. Most description vectors either agree with the title or have only a very small margin over automation. Raising the description weight would not reliably fix the observed process-category errors.

The first calibration target should be the category text:

1. Narrow `automation` to implementation-oriented technical automation such as RPA, scripting, APIs, integrations, workflow engines, and low-code platforms. Avoid making generic business-process work sufficient by itself.
2. Strengthen `process_management` with business analysis, BPM, process governance, continuous improvement, workflow analysis, process ownership, and operational excellence, while distinguishing it from technical automation implementation.
3. Extend `supply_chain` with demand planning, fulfillment, procurement, production planning, forecasting, and inventory planning.
4. Re-run this exact evaluator after changing only category descriptions.

Do not introduce a threshold, alter the pre-score, add Career Profiles, or change n8n before that calibration run.

## Reproduction

With LM Studio running on `127.0.0.1:1234` and the configured model loaded:

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_categories.py --live --results-per-query 5 --limit 30
```

The evaluator prints measurements to stdout and does not persist raw descriptions or embedding vectors.
