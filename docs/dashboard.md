# Job Radar dashboard

Start the existing service as usual (`python -m api.main`) and open
`http://127.0.0.1:8001/ui/`. The dashboard automatically loads `/jobs/cached`
from the same origin. No new frontend dependencies, build step, or CORS
configuration is required.

Use **Jobs importieren → Neue Suche starten** to run the existing `/jobs`
scrape. **Cache laden** reads the latest results without triggering a scrape.
If there are no cached jobs, the dashboard clearly shows fictitious examples;
they have no application links. The JSON import also accepts `cache/jobs_cache.json`
and arrays of canonical or legacy Job Radar jobs. Importing replaces the current
browser dataset; export it first if you want to keep a copy.

Search, source / level / minimum-score filters, career direction tabs, sorting,
and detail views work on the loaded dataset. The company watchlist uses the
API's `in_watchlist` field; personal bookmarks and seen status are separate
browser-local state. No application tracking or email sending is simulated.

The dashboard displays the deterministic pre-score and its original components.
Semantic career directions and categories remain separate. Similarity is never
shown as a percentage fit. The existing disabled LLM evaluation is not enabled.

The same frontend is also hosted privately through Sites. That copy can import
JSON or connect to an API reachable from the visitor's browser. It does not host
the Python scraper, n8n, LM Studio, or your private cache. Cross-origin API use
requires an explicit CORS allowlist and a browser-compatible HTTPS address;
local `/ui/` usage works without those changes. Do not publish the unauthenticated
local API to the internet just to connect the dashboard.

Jobs, bookmarks, seen status, and the API address are stored in this browser's
local storage. No data is synchronized between browsers. The existing API
endpoints, scoring, source adapters, configuration, and n8n email workflow are
preserved.

