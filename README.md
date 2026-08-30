# Job Radar
A personal job radar for junior-to-mid roles that scrapes Indeed and LinkedIn via `python-jobspy`, filters and scores matches deterministically, and exposes the result as JSON for an n8n downstream consumer.

## What This Project Does
- Scrapes listings from Indeed and LinkedIn through `python-jobspy`.
- Runs broad discovery queries from `config.yaml` across configured locations.
- Excludes only clear seniority and unsuitable employment-type title patterns before scoring.
- Calculates an explainable component-based `0-100` pre-score without using it as an acceptance gate.
- Adds semantic role-category and career-profile similarities through an optional local LM Studio embedding service.
- Provides a disabled-by-default structured LM Studio evaluation foundation for the next benchmark phase.
- Serves fresh, cached, and aggregated results through FastAPI endpoints backed by a local JSON cache.

## Architecture
```text
config.yaml --> scraper orchestration --> JobSpy source --> normalization --> canonical Job
                                                                            --> hard filter --> pre-score
                                                                                               --> semantic categories
                                                                                               --> career profiles --> V1 adapter --> /jobs
                                                                                                                     |
                                                                                                             JSON cache
                                                                                                                     |
                                                                                                                     v
                                                                                                n8n --> Ollama reranking --> HTML email
```
The API scoring step is rule-based on purpose: it is deterministic, free to run, and easy to test. That makes it a good fit for a local screening service with transparent ranking logic. Optional LLM-based reranking is included in the `n8n/` workflow as a downstream presentation layer, not as part of the API scoring logic.

## End-to-End Flow with n8n
The repository includes a sanitized workflow in `n8n/workflow.json`.

1. FastAPI runs a fresh scrape through `GET /jobs`, keeps every job that passes the hard filters, and writes the local cache.
2. n8n reads the cached payload from `GET /jobs/cached`.
3. Jobs are flattened, split into batches, and scored again by a local Ollama model using a profile-specific prompt.
4. Relevant jobs are aggregated into a weekly HTML report and sent by email.

This split keeps the API deterministic and testable while still letting the final shortlist benefit from LLM-based prioritization.

## Setup
Windows PowerShell:
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Unix shell:
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Install n8n separately if you want to use the bundled workflow:
```bash
npm install -g n8n
```

Or run n8n with Docker instead of a global install:
```bash
docker run --name n8n -p 5678:5678 -v ~/.n8n:/home/node/.n8n docker.n8n.io/n8nio/n8n
```

## Running
Start the API server:
```bash
python -m uvicorn api.main:app --port 8001
```

Start n8n separately through its CLI or Docker when using the bundled workflow.

Run a scrape directly and print JSON to stdout:
```bash
python -m api.scraper
```

Run tests:
```bash
pytest tests/ -v
```

## API Endpoints
| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | `GET` | Health check |
| `/jobs` | `GET` | Runs a fresh scrape and writes the cache |
| `/jobs/cached` | `GET` | Returns the last cached scrape result |
| `/jobs/stats` | `GET` | Returns job aggregates and overall/per-source description availability |

## Example Response
```json
{
  "jobs": [
    {
      "title": "Junior Automation Engineer",
      "company": "Example GmbH",
      "location": "Karlsruhe, Germany",
      "url": "https://example.com/jobs/1",
      "source": "linkedin",
      "date_posted": "2026-04-20",
      "is_remote": false,
      "description": "Build digital transformation and process optimization solutions with Python, REST APIs and Azure integrations.",
      "description_status": "available",
      "description_length": 5842,
      "description_source": "search_result",
      "level": "Entry",
      "profile": "AI & Data Engineering",
      "in_watchlist": false,
      "skills_required": [],
      "pre_score": 72,
      "pre_score_components": {
        "total": 72,
        "seniority": {"score": 25, "max_score": 25, "matched_signals": ["junior"], "notes": ["explicit junior or entry-level signal in title"]},
        "technologies": {"score": 15, "max_score": 30, "matched_signals": ["python", "azure", "rest_api"], "notes": ["description: python", "description: azure", "description: rest_api"]},
        "role": {"score": 15, "max_score": 25, "matched_signals": ["automation", "digitalization", "process_optimization", "integration"], "notes": ["title: automation", "description: digitalization", "description: process_optimization", "description: integration"]},
        "location": {"score": 17, "max_score": 20, "matched_signals": ["preferred_region", "onsite"], "notes": ["onsite role in preferred region"]}
      },
      "categories": [
        {"name": "automation", "similarity": 0.83, "title_similarity": 0.88, "description_similarity": 0.80},
        {"name": "process_management", "similarity": 0.76, "title_similarity": 0.70, "description_similarity": 0.80}
      ],
      "embedding_input": "title_and_description",
      "embedding_model": "text-embedding-qwen3-embedding-0.6b",
      "embedding_status": "success",
      "score": 72,
      "score_reason": "Seniority 25/25, Technologies 15/30, Role 15/25, Location 17/20"
    },
    {
      "title": "Backend Developer",
      "company": "Sample Tech AG",
      "location": "Karlsruhe, Germany",
      "url": "https://example.com/jobs/2",
      "source": "indeed",
      "date_posted": "2026-04-19",
      "is_remote": true,
      "description": "FastAPI and Docker role focused on backend automation services.",
      "description_status": "available",
      "description_length": 4310,
      "description_source": "search_result",
      "level": "Mid",
      "profile": "Software Development",
      "in_watchlist": true,
      "skills_required": [],
      "pre_score": 50,
      "pre_score_components": {
        "total": 50,
        "seniority": {"score": 17, "max_score": 25, "matched_signals": [], "notes": ["no explicit seniority signal; neutral score applied"]},
        "technologies": {"score": 10, "max_score": 30, "matched_signals": ["fastapi", "docker"], "notes": ["description: fastapi", "description: docker"]},
        "role": {"score": 3, "max_score": 25, "matched_signals": ["automation"], "notes": ["description: automation"]},
        "location": {"score": 20, "max_score": 20, "matched_signals": ["remote"], "notes": ["remote work model detected"]}
      },
      "score": 50,
      "score_reason": "Seniority 17/25, Technologies 10/30, Role 3/25, Location 20/20"
    }
  ],
  "total_found": 124,
  "total_after_filter": 2,
  "scraped_at": "2026-04-21T08:30:00+00:00",
  "profiles_searched": ["AI & Data Engineering", "Software Development"],
  "failed_searches": 0,
  "hard_filter_rejections": {"excluded_seniority": 8},
  "description_stats": {
    "total": 2,
    "available": 2,
    "missing": 0,
    "by_source": {
      "indeed": {"available": 1, "missing": 0},
      "linkedin": {"available": 1, "missing": 0}
    }
  }
}
```

## Configuration
| Field | Effect |
| --- | --- |
| `search.query_groups[].queries` | Broad discovery queries; groups only preserve a legacy result label |
| `search.locations`, `results_per_query`, `hours_old` | JobSpy search scope |
| `search.linkedin_fetch_description` | Uses JobSpy's slower LinkedIn detail fetch; disabled by default |
| `hard_filters.excluded_title_terms` | Adds explicit project-specific exclusions to the explainable defaults |
| `signals.role_terms`, `signals.technologies` | Named positive evidence retained in the pre-score components; never acceptance requirements |
| `pre_score.seniority` | Explicit junior evidence and neutral fallback, maximum 25 points |
| `pre_score.technologies` | Points per unique named technology signal, capped at 30 |
| `pre_score.role` | Stronger title evidence and weaker description evidence, capped at 25 |
| `pre_score.location` | Transparent remote, hybrid, preferred-region, other-region, and unknown scores, capped at 20 |
| `embeddings` | LM Studio endpoint/model, vector dimensions, instruction, and title/description weights |
| `llm_evaluation` | Disabled V2.7.1 LM Studio chat endpoint, future model identifier, timeout, and temperature |
| `config/categories.yaml` | English semantic descriptions embedded once and retained as vectors only in process memory |
| `config/candidate_profile.yaml` | Authoritative candidate facts kept separate from target-role preferences |
| `companies` | Optional watchlist metadata; career preference is not part of the V2.4 pre-score |

## Scoring At a Glance
Every accepted job receives four stored components: seniority `0–25`, technologies `0–30`, role signals `0–25`, and location/work model `0–20`. Each component contains its score, maximum, matched signal names, and notes. Missing seniority and location information receive explicit neutral values rather than automatic rejection. The API retains every hard-filter-accepted job regardless of its pre-score. The old `score` and `score_reason` fields mirror the new result only for compatibility with the existing n8n workflow.

## Semantic Category Classification

V2.5 adds an observational semantic layer after the deterministic pre-score. It does not reject jobs, alter the pre-score, or interpret cosine similarity as a percentage fit. The configured categories are embedded once per process and cached in memory. Raw vectors are never attached to canonical jobs, API responses, or the JSON cache.

The title is always embedded as an instructed query. An available description is embedded separately. Each category result stores title similarity, optional description similarity, and a combined similarity sorted from strongest to weakest:

```text
description available:  0.4 * title similarity + 0.6 * description similarity
description missing:    1.0 * title similarity
```

The weights and English task instruction are configurable. Qwen3-Embedding-0.6B is the first candidate because it supports multilingual input, instructions, and up to 1024 dimensions. To use it:

1. Install and start LM Studio's local server on port `1234`.
2. Download/load a Qwen3-Embedding-0.6B embedding build supported by LM Studio.
3. Read the exact identifier from `GET http://localhost:1234/v1/models` and set `embeddings.model` in `config.yaml`.

If the server cannot be reached, the model is unavailable, or a response is invalid, each job remains in the result with empty `categories` and `embedding_status` set to `unavailable` or `error`. Successful results expose `embedding_input` as either `title_only` or `title_and_description` and identify the configured model. A similarity threshold is deliberately absent until real-job calibration has been completed.

The initial live validation and category calibration are documented in [`docs/semantic-validation-v2.5.1.md`](docs/semantic-validation-v2.5.1.md) and [`docs/semantic-validation-v2.5.2.md`](docs/semantic-validation-v2.5.2.md). The reusable live evaluator prints results without persisting raw descriptions or vectors:

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_categories.py --live --results-per-query 5 --limit 30
```

V2.5.3 adds a committed 30-case semantic regression fixture with explicit primary,
acceptable secondary, multi-category, and no-taxonomy-fit labels. Its evaluator
reports Top-1 accuracy, Top-2 recall, and mean best-primary rank. The baseline is
25/27 Top-1 and 26/27 Top-2; details are in
[`docs/semantic-regression-v2.5.3.md`](docs/semantic-regression-v2.5.3.md).

```powershell
.venv\Scripts\python.exe scripts\evaluate_semantic_regression.py
```

## Career Profile Matching

V2.6 adds career-profile similarities alongside semantic categories. Categories
describe the role; profiles describe its proximity to one of four target career
directions configured in `config/career_profiles.yaml`. Both layers use the same
local model and title/description weighting but retain separate matches, input
metadata, and service status. Profile matches never reject a job or alter its
pre-score.

The committed 24-case benchmark reaches 21/22 Top-1 and 22/22 Top-2 on labelled
profile matches. The full benchmark and 16-job live sample are documented in
[`docs/career-profile-validation-v2.6.md`](docs/career-profile-validation-v2.6.md).

```powershell
.venv\Scripts\python.exe scripts\evaluate_career_profiles.py
```

V2.6.1 adds confusion matrices and similarity margins and validates the profiles
against a local ignored snapshot of 35 manually labelled real jobs. The current
profile wording retained 16/16 Top-1 matches, while an experimental version without
seniority wording fell to 12/16. The committed profiles therefore remain unchanged.
See [`docs/career-profile-real-world-v2.6.1.md`](docs/career-profile-real-world-v2.6.1.md).

## Structured LLM Evaluation Foundation

V2.7.1 introduces the isolated foundation for a later qualitative job evaluation.
It is not yet called by the scraping pipeline or exposed to n8n. Candidate facts,
evidence-backed skills, professional strengths, evaluation guidance, and target
preferences are validated separately in `config/candidate_profile.yaml`.
The prompt passes the full normalized description, deterministic pre-score with its
components, semantic categories, career-profile matches, and description data quality
without combining their scores.

LM Studio is addressed through its OpenAI-compatible `/chat/completions` endpoint.
The request supplies the strict JSON Schema generated from `LLMEvaluation`. Returned
content is treated as untrusted and parsed directly by Pydantic: invalid output gets
exactly one retry and is otherwise recorded as an error without regex repair. A service
outage produces an `unavailable` attempt rather than dropping the job. Missing
descriptions require a `preliminary` evaluation; available descriptions require a
`complete` evaluation.

The feature remains disabled and has no selected model in `config.yaml`. V2.7.2 will
compare at least two local models against manually labelled real jobs before one is
selected or pipeline integration begins.

### Real-World LLM Benchmark Dataset

V2.7.2a freezes a private, deliberately balanced 24-job benchmark before any chat
model output is inspected. It contains six manual labels for each recommendation
class (`strong_match`, `review`, `weak_match`, and `reject`), with 18 complete job
descriptions and six `title_only` preliminary cases. Manual labels include reference
scores, expected strengths, mandatory and optional gaps, experience requirements,
experience-gap judgments, edge-case tags, and notes.

Complete postings and labels remain ignored under `data/evaluation/`. The committed
schema validates the exact class and description balance, matching job/label IDs,
the frozen candidate-profile hash, successful category/profile embeddings, one shared
embedding model, and the absence of prior LLM results. Capture hints never become
manual labels, and no chat model is called by either dataset script.

```powershell
.venv\Scripts\python.exe scripts\capture_llm_benchmark_pool.py
.venv\Scripts\python.exe scripts\finalize_llm_benchmark.py
```

The frozen local dataset currently covers 14 must-have-gap cases, 12 nice-to-have-gap
cases, eight explicit required-experience cases, three preferred-experience cases,
six title-only cases, and several generic or misleading-title cases. Model selection
and repeated evaluation belong to V2.7.2b.

### Prompt Calibration

V2.7.2b-1 separates prompt calibration from later model selection. The private frozen
subset contains exactly eight jobs (two per recommendation class) and covers mandatory
and optional gaps, required and preferred experience, missing descriptions, and
multi-signal boundary cases. Its file hashes bind it to the unchanged 24-job snapshot
and manual labels.

Three prompt families are benchmarked against identical candidate, job, deterministic,
and semantic inputs: `minimal`, `evidence_first`, and `conservative`. Models and runtime
settings live only in `config/llm_benchmark.yaml`; the benchmark logic contains no model
IDs. The current one-run screening baseline uses LM Studio's local-device llama.cpp
runtime, 12,288 context tokens, maximum GPU offload, one parallel request, temperature
0.2, 4,000 output tokens, model-default reasoning, strict JSON Schema, and seed 42.
The configured anchor IDs are the IDs reported by the local `/v1/models` endpoint.

The runner validates all frozen inputs before contacting a model, records each result
incrementally in the ignored evaluation directory, and reports recommendation and
ordinal quality, all score MAEs, experience-gap accuracy, mandatory/optional gap
precision and recall, explicit absent-skill hallucinations, title-only behavior, schema
retries and failures, latency, and repeated-run stability.

```powershell
.venv\Scripts\python.exe scripts\calibrate_llm_prompts.py --dry-run
.venv\Scripts\python.exe scripts\calibrate_llm_prompts.py
```

Use `--runs 2` only for confirmation after the initial screen. A benchmark prompt is
frozen only after it performs robustly across both anchors; this phase does not integrate
LLM output into scraping or n8n.

The one-run screen used the locally available `ornith-1.5-9b` and
`ornith-1.5-35b-a3b` anchors. `qwen3.8-27b` was probed first but excluded from prompt
calibration after its first request reached the fixed 300-second timeout. Across the
two practical anchors, `evidence_first` had the best screening recommendation accuracy,
lowest ordinal error, fewest large recommendation errors, best mandatory-gap recall,
and lowest title-only gap-invention rate. It is frozen in the benchmark config with its
prompt hash for subsequent model screening.

The selected prompt was then confirmed with a second seed on both anchors (32 planned
observations, 29 successful). Combined confirmation metrics were 37.9% exact
recommendation accuracy, 1.03 mean ordinal error, 61.9% experience-gap accuracy, zero
detected absent-skill hallucinations, 100% preliminary-status accuracy, 12.5%
title-only invented-gap rate, 50% run-to-run recommendation stability, 9.4% failure
rate, and 56.4 seconds median latency. These are calibration results, not deployment
quality: model screening and reasoning/runtime calibration remain necessary before any
pipeline integration.

```powershell
.venv\Scripts\python.exe scripts\summarize_llm_prompt_calibration.py `
  --prompt evidence_first --runs-per-case 2 `
  data\evaluation\llm-benchmark-results\prompt-calibration-screening.json `
  data\evaluation\llm-benchmark-results\prompt-calibration-anchor-35b.json `
  data\evaluation\llm-benchmark-results\prompt-calibration-evidence-confirmation.json
```

### Local Model Runtime Calibration and Screening

V2.7.2b-2 separates model-native runtime settings from the frozen evaluation task.
The prompt, prompt hash, candidate profile, eight-job subset, labels, and response
schema remain unchanged, while context length, output budget, timeout, and reasoning
effort are persisted per model. LM Studio models are loaded exclusively for each block;
an already-loaded model is reloaded when its actual context does not match the profile.
Embedding instances are left untouched.

The current screening profiles use 65,536 context tokens and up to 8,000 output tokens.
The larger budget fixed failures where reasoning consumed the former output allowance.
The calibrated profiles are Ornith 1.5 9B with minimal reasoning, Ornith 1.5 35B-A3B
with minimal reasoning, and Qwen 3.8 27B with reasoning disabled. All three completed
two frozen eight-job runs without timeout, failed response, or detected candidate
hallucination.

Across the combined 16 observations per model, Ornith 35B-A3B achieved 62.5% exact
recommendation accuracy, no large recommendation errors, 75% recommendation stability,
and 36.0 seconds median latency. Ornith 9B achieved 68.75% accuracy, two large errors,
87.5% stability, and 41.4 seconds median latency. Qwen 27B was fastest at 19.8 seconds,
but reached 50% accuracy, two large errors, and 75% stability. The generic ranking
therefore recommends the two Ornith profiles for the later full 24-job benchmark. This
is a finalist recommendation, not a final deployment model choice.

```powershell
.venv\Scripts\python.exe scripts\calibrate_llm_runtime.py --dry-run
.venv\Scripts\python.exe scripts\screen_llm_models.py --run-index 1
.venv\Scripts\python.exe scripts\screen_llm_models.py --run-index 2
.venv\Scripts\python.exe scripts\summarize_llm_model_screening.py `
  data\evaluation\llm-benchmark-results\model-screening-run-1.json `
  data\evaluation\llm-benchmark-results\model-screening-run-2.json
```

## Description Data Quality

Canonical jobs retain `description_status`, normalized `description_length`, and `description_source`. Missing descriptions never reject a job. Every scrape reports overall and per-source availability through `description_stats`.

A live sample on 2026-08-30 produced:

| Sample | Runtime | Available | Missing |
| --- | ---: | ---: | ---: |
| Indeed, normal search | part of 13.31 s mixed run | 25 | 0 |
| LinkedIn, normal search | part of 13.31 s mixed run | 0 | 25 |
| LinkedIn-only, normal | 0.69 s | 0 | 10 |
| LinkedIn-only, JobSpy detail fetch | 8.33 s | 10 | 0 |

No request errors or HTTP 429 responses occurred in these small samples. The enriched LinkedIn run was roughly 12 times slower than the equivalent normal run, so `linkedin_fetch_description` remains disabled by default. The planned embedding rule is explicit: missing descriptions use `title_only`; available descriptions use `title_and_description`. Blanket enrichment is deferred in favor of targeted enrichment after a later preselection step.

## Tests
The test suite covers canonical normalization, stable IDs, JobSpy isolation, structured hard-filter reasons, broad discovery without keyword gates, all pre-score components, semantic cosine similarity and weighting, cached category and career-profile vectors, regression-dataset validation and ranking metrics, private LLM-benchmark balance and freeze validation, independent embedding-service failure states, strict LLM output validation and retry behavior, V1 compatibility, `nan` normalization, level inference, and model defaults. Run it with `pytest tests/ -v`.

## Limitations
- Focused on German/DACH search coverage, currently configured around Karlsruhe, Germany.
- Depends on `python-jobspy`, so rate limits and source-site markup changes can affect Indeed and LinkedIn scraping.
- Some source results omit the full description. They remain eligible and are explicitly measured through description metadata and per-source statistics.
- LinkedIn detail enrichment is deliberately disabled by default because the measured sample was substantially slower and larger runs may encounter rate limits.
- Semantic categories remain observational signals and never gate a job in V2.5.
- Local semantic classification requires a running LM Studio server and a matching configured embedding model; service failure is nonfatal.
- Structured LLM evaluation is foundation-only and disabled until the V2.7.2 model benchmark is complete.
- No persistence layer beyond a local file cache.
- No authentication on the FastAPI endpoints; intended for local or internal use.

## Project Structure
```text
api/
  main.py          # FastAPI app + endpoints
  scraper.py       # broad search orchestration and hard-filter integration
  scorer.py        # explainable component-based pre-score
  embeddings.py    # LM Studio client + cached category/profile matching
  llm_evaluation.py # structured prompt, chat client, validation, and nonfatal statuses
  llm_benchmark.py # private benchmark schemas, balance, and freeze validation
  llm_model_screening.py # runtime profiles, observations, metrics, and selection
  lm_studio_runtime.py # exclusive model loading and context verification
  models.py        # canonical and V1 response models
  normalization.py # raw source data to canonical Job
  compatibility.py # canonical Job to existing V1 API response
  filters.py        # explainable high-confidence hard exclusions
  observability.py  # description availability summaries by source
  semantic_benchmark.py # persisted semantic labels and ranking metrics
  sources/jobspy.py # JobSpy-specific fetching
config.yaml     # discovery, filters, signals, scoring, embedding, and LLM settings
config/
  candidate_profile.yaml # authoritative facts separated from role preferences
  categories.yaml # semantic category descriptions
  career_profiles.yaml # target career-direction descriptions
docs/
  semantic-validation-v2.5.1.md # first real-model validation report
  semantic-validation-v2.5.2.md # category calibration report
  semantic-regression-v2.5.3.md # frozen benchmark baseline
  career-profile-validation-v2.6.md # profile benchmark and live validation
  career-profile-real-world-v2.6.1.md # ignored real-world benchmark and A/B result
n8n/            # sanitized workflow + n8n-specific docs
scripts/
  evaluate_semantic_categories.py # reproducible reference/live semantic evaluation
  evaluate_semantic_regression.py # frozen labelled benchmark evaluation
  evaluate_career_profiles.py # career-profile benchmark and optional live sample
  capture_career_profile_snapshot.py # ignored real-job snapshot capture
  label_career_profile_snapshot.py # apply local manual labels
  capture_llm_benchmark_pool.py # targeted private pre-model job capture
  finalize_llm_benchmark.py # freeze selected jobs and validate manual labels
  calibrate_llm_runtime.py # per-model reasoning and runtime calibration
  screen_llm_models.py # frozen eight-job generic model screening
  summarize_llm_model_screening.py # repeated-run stability and finalist ranking
tests/          # pytest suite
pyproject.toml
```
