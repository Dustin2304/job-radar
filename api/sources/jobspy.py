"""JobSpy-specific fetching boundary."""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore", module=r"jobspy.*")

try:
    from jobspy import scrape_jobs
except ImportError:
    scrape_jobs = None

KM_TO_MILES = 0.621371


def fetch_jobs(
    *,
    search_query: str,
    location: str,
    country: str,
    results_wanted: int,
    hours_old: int,
    radius_km: int = 0,
    is_remote: bool = False,
) -> list[dict]:
    """Fetch one JobSpy result set and return source-specific raw dictionaries."""
    if scrape_jobs is None:
        raise RuntimeError("python-jobspy not installed. Run: pip install python-jobspy")

    scrape_kwargs: dict[str, object] = {
        "site_name": ["indeed", "linkedin"],
        "search_term": search_query,
        "location": location,
        "results_wanted": results_wanted,
        "hours_old": hours_old,
        "country_indeed": country,
        "description_format": "markdown",
        "verbose": 0,
    }
    if is_remote:
        scrape_kwargs["is_remote"] = True
    if radius_km:
        scrape_kwargs["distance"] = int(radius_km * KM_TO_MILES)

    dataframe = scrape_jobs(**scrape_kwargs)
    if dataframe is None or dataframe.empty:
        return []
    return dataframe.to_dict(orient="records")


__all__ = ["fetch_jobs"]
