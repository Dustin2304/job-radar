# Job Radar
A personal job radar for junior-to-mid roles that scrapes Indeed and LinkedIn via `python-jobspy`, filters and scores matches deterministically, and exposes the result as JSON for an n8n downstream consumer.

## What This Project Does
- Scrapes listings from Indeed and LinkedIn through `python-jobspy`.
- Runs broad discovery queries from `config.yaml` across configured locations.
- Excludes only clear seniority and unsuitable employment-type title patterns before scoring.
- Calculates an explainable component-based `0-100` pre-score without using it as an acceptance gate.
- Serves fresh, cached, and aggregated results through FastAPI endpoints backed by a local JSON cache.

## Architecture
```text
config.yaml --> scraper orchestration --> JobSpy source --> normalization --> canonical Job
                                                                            --> hard filter --> pre-score --> V1 adapter --> /jobs
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
| `/jobs/stats` | `GET` | Returns aggregates: `by_profile`, `by_source`, `watchlist_count` |

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
  "hard_filter_rejections": {"excluded_seniority": 8}
}
```

## Configuration
| Field | Effect |
| --- | --- |
| `search.query_groups[].queries` | Broad discovery queries; groups only preserve a legacy result label |
| `search.locations`, `results_per_query`, `hours_old` | JobSpy search scope |
| `hard_filters.excluded_title_terms` | Adds explicit project-specific exclusions to the explainable defaults |
| `signals.role_terms`, `signals.technologies` | Named positive evidence retained in the pre-score components; never acceptance requirements |
| `pre_score.seniority` | Explicit junior evidence and neutral fallback, maximum 25 points |
| `pre_score.technologies` | Points per unique named technology signal, capped at 30 |
| `pre_score.role` | Stronger title evidence and weaker description evidence, capped at 25 |
| `pre_score.location` | Transparent remote, hybrid, preferred-region, other-region, and unknown scores, capped at 20 |
| `companies` | Optional watchlist metadata; career preference is not part of the V2.4 pre-score |

## Scoring At a Glance
Every accepted job receives four stored components: seniority `0–25`, technologies `0–30`, role signals `0–25`, and location/work model `0–20`. Each component contains its score, maximum, matched signal names, and notes. Missing seniority and location information receive explicit neutral values rather than automatic rejection. The API retains every hard-filter-accepted job regardless of its pre-score. The old `score` and `score_reason` fields mirror the new result only for compatibility with the existing n8n workflow.

## Tests
The test suite covers canonical normalization, stable IDs, JobSpy isolation, structured hard-filter reasons, broad discovery without keyword gates, all pre-score components, representative scoring fixtures, V1 compatibility, `nan` normalization, level inference, and model defaults. Run it with `pytest tests/ -v`.

## Limitations
- Focused on German/DACH search coverage, currently configured around Karlsruhe, Germany.
- Depends on `python-jobspy`, so rate limits and source-site markup changes can affect Indeed and LinkedIn scraping.
- Some source results omit the full description. They remain eligible; enrichment and an explicit description status are planned before semantic and LLM evaluation.
- No persistence layer beyond a local file cache.
- No authentication on the FastAPI endpoints; intended for local or internal use.

## Project Structure
```text
api/
  main.py          # FastAPI app + endpoints
  scraper.py       # broad search orchestration and hard-filter integration
  scorer.py        # explainable component-based pre-score
  models.py        # canonical and V1 response models
  normalization.py # raw source data to canonical Job
  compatibility.py # canonical Job to existing V1 API response
  filters.py        # explainable high-confidence hard exclusions
  sources/jobspy.py # JobSpy-specific fetching
config.yaml     # discovery, hard filters, positive signals, pre-score rules
n8n/            # sanitized workflow + n8n-specific docs
tests/          # pytest suite
pyproject.toml
```
