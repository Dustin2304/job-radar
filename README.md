# Job Radar
A personal job radar for junior-to-mid roles that scrapes Indeed and LinkedIn via `python-jobspy`, filters and scores matches deterministically, and exposes the result as JSON for an n8n downstream consumer.

## What This Project Does
- Scrapes listings from Indeed and LinkedIn through `python-jobspy`.
- Runs profile-based keyword searches from `config.yaml` across configured locations.
- Excludes senior, internship, trainee, and other unwanted title patterns before scoring.
- Scores remaining jobs with a rule-based `0-100` relevance model and applies profile-specific thresholds.
- Serves fresh, cached, and aggregated results through FastAPI endpoints backed by a local JSON cache.

## Architecture
```text
config.yaml --> scraper orchestration --> JobSpy source --> normalization --> canonical Job
                                                                            --> V1 adapter --> filter --> scorer --> /jobs
                                                                                                              |
                                                                                                      JSON cache
                                                                                                              |
                                                                                                              v
                                                                                         n8n --> Ollama reranking --> HTML email
```
The API scoring step is rule-based on purpose: it is deterministic, free to run, and easy to test. That makes it a good fit for a local screening service with transparent ranking logic. Optional LLM-based reranking is included in the `n8n/` workflow as a downstream presentation layer, not as part of the API scoring logic.

## End-to-End Flow with n8n
The repository includes a sanitized workflow in `n8n/workflow.json`.

1. FastAPI runs a fresh scrape through `GET /jobs` and writes the local cache.
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
Start the API server and n8n together:
```powershell
scripts/run.ps1
```
```bash
scripts/run.sh
```

Both scripts start `n8n` and the FastAPI app together. They expect the `n8n` CLI to be installed and available in `PATH`. If you prefer Docker for n8n, start the container separately and run only the FastAPI server.

Start only the API server:
```bash
python -m uvicorn api.main:app --port 8001
```

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
| `locations[].city`, `radius_km`, `country` | Search area for each `jobspy` call |
| `scoring.threshold_it` | Minimum score for IT profiles; lower results are dropped |
| `scoring.threshold_non_it` | Minimum score for non-IT profiles with a higher hurdle |
| `profiles[].name`, `keywords`, `weight` | Search profile definition; `weight < 1.0` marks non-IT fallback profiles and reduces the effective score |
| `filters.exclude_title_keywords` | Extends the hardcoded senior and internship title filters |
| `companies` | Optional watchlist; matching jobs get `in_watchlist: true` and a score bonus |

## Scoring At a Glance
Each job starts at `30` points. Title matches add up to `35`, description matches add up to `25`, watchlist matches add `8`, and junior or entry-style titles add `5`. The profile `weight` is applied to the accumulated score, which lets non-IT fallback profiles rank lower without separate logic. All scoring rules live in `api/scorer.py` and can be adjusted without changing the API surface.

## Tests
11 unit tests cover scorer weighting, filter word boundaries, `nan` normalization, level inference, and model defaults. Run them with `pytest tests/ -v`.

## Limitations
- Focused on German/DACH search coverage, currently configured around Karlsruhe, Germany.
- Depends on `python-jobspy`, so rate limits and source-site markup changes can affect Indeed and LinkedIn scraping.
- No persistence layer beyond a local file cache.
- No authentication on the FastAPI endpoints; intended for local or internal use.

## Project Structure
```text
api/
  main.py          # FastAPI app + endpoints
  scraper.py       # search orchestration, legacy filter and threshold gate
  scorer.py        # rule-based scoring
  models.py        # canonical and V1 response models
  normalization.py # raw source data to canonical Job
  compatibility.py # canonical Job to existing V1 API response
  sources/jobspy.py # JobSpy-specific fetching
config.yaml     # profiles, locations, thresholds
n8n/            # sanitized workflow + n8n-specific docs
scripts/        # run.sh / run.ps1
tests/          # pytest suite
pyproject.toml
```
