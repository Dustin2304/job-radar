# Job Radar
A personal job radar for junior-to-mid roles that scrapes Indeed and LinkedIn via `python-jobspy`, filters and scores matches deterministically, and exposes the result as JSON for an n8n downstream consumer.

## What This Project Does
- Scrapes listings from Indeed and LinkedIn through `python-jobspy`.
- Runs broad discovery queries from `config.yaml` across configured locations.
- Excludes only clear seniority and unsuitable employment-type title patterns before scoring.
- Adds a temporary rule-based `0-100` score as information without using it as an acceptance gate.
- Serves fresh, cached, and aggregated results through FastAPI endpoints backed by a local JSON cache.

## Architecture
```text
config.yaml --> scraper orchestration --> JobSpy source --> normalization --> canonical Job
                                                                            --> hard filter --> V1 adapter --> legacy score --> /jobs
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
      "title": "AI Engineer",
      "company": "Example GmbH",
      "location": "Karlsruhe, Germany",
      "url": "https://example.com/jobs/1",
      "source": "linkedin",
      "date_posted": "2026-04-20",
      "is_remote": false,
      "description": "Build internal LLM and Python services for document workflows.",
      "level": "Entry",
      "profile": "AI & Data Engineering",
      "in_watchlist": false,
      "skills_required": [],
      "score": 85,
      "score_reason": "Ai Engineer, LLM, Python, Entry-Level"
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
      "score": 76,
      "score_reason": "Backend Developer, FastAPI, Docker, Watchlist, Mid-Level"
    }
  ],
  "total_found": 124,
  "total_after_filter": 2,
  "scraped_at": "2026-04-21T08:30:00+00:00",
  "profiles_searched": ["AI & Data Engineering", "Software Development"],
  "failed_searches": 0
}
```

## Configuration
| Field | Effect |
| --- | --- |
| `search.query_groups[].queries` | Broad discovery queries; groups only preserve a legacy result label |
| `search.locations`, `results_per_query`, `hours_old` | JobSpy search scope |
| `hard_filters.excluded_title_terms` | Adds explicit project-specific exclusions to the explainable defaults |
| `signals.role_terms`, `signals.technologies` | Positive evidence for the temporary legacy score; never acceptance requirements |
| `legacy_scoring` | Temporary base score, caps, and bonuses until the explainable V2 pre-score replaces it |
| `companies` | Optional watchlist; matching jobs get `in_watchlist: true` and a score bonus |

## Scoring At a Glance
Each job currently starts at `30` points. Configured role signals add up to `35`, technology signals add up to `25`, watchlist matches add `8`, and junior or entry-style titles add `5`. Discovery groups do not modify the score, and the score does not remove jobs from the API result. This temporary score will be replaced by an explainable component-based pre-score in a later milestone.

## Tests
The test suite covers canonical normalization, stable IDs, JobSpy isolation, structured hard-filter reasons, broad discovery without keyword gates, V1 compatibility, positive scoring signals, `nan` normalization, level inference, and model defaults. Run it with `pytest tests/ -v`.

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
  scorer.py        # rule-based scoring
  models.py        # canonical and V1 response models
  normalization.py # raw source data to canonical Job
  compatibility.py # canonical Job to existing V1 API response
  filters.py        # explainable high-confidence hard exclusions
  sources/jobspy.py # JobSpy-specific fetching
config.yaml     # discovery, hard filters, positive signals, legacy scoring
n8n/            # sanitized workflow + n8n-specific docs
tests/          # pytest suite
pyproject.toml
```
