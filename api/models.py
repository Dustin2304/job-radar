from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CategoryMatch(BaseModel):
    name: str
    similarity: float


class ProfileMatch(BaseModel):
    name: str
    similarity: float


class ScoreComponents(BaseModel):
    profile: float = 0
    category: float = 0
    seniority: float = 0
    skills: float = 0
    location: float = 0
    bonus: float = 0


class FilterReason(BaseModel):
    code: str
    field: str | None = None
    value: str | None = None


class FilterResult(BaseModel):
    accepted: bool
    reasons: list[FilterReason] = Field(default_factory=list)


class Job(BaseModel):
    """Canonical source-independent representation used inside the application."""

    id: str
    source_id: str | None = None

    title: str
    company: str
    description: str
    url: str

    location: str | None = None
    is_remote: bool = False
    remote_type: str | None = None

    source: str
    date_posted: str | None = None
    search_queries: list[str] = Field(default_factory=list)

    categories: list[CategoryMatch] = Field(default_factory=list)
    profile_matches: list[ProfileMatch] = Field(default_factory=list)

    hard_filter_passed: bool = True
    rejection_reasons: list[FilterReason] = Field(default_factory=list)

    pre_score: float | None = None
    score_components: ScoreComponents | None = None
    llm_score: float | None = None
    llm_recommendation: str | None = None
    review_status: str = "NEW"


class JobResult(BaseModel):
    title: str = Field(description="Job title as listed in the posting")
    company: str = Field(description="Name of the hiring company")
    location: str = Field(description="Job location (city, country, or 'Remote')")
    url: str = Field(description="Direct link to the job posting")
    source: Literal["indeed", "linkedin"] = Field(description="Platform where the job was found")
    date_posted: str = Field(description="Posting date as returned by the source platform")
    is_remote: bool = Field(description="Whether the position is fully or partially remote")
    description: str = Field(max_length=500, description="Short excerpt of the job description (max 500 characters)")
    level: str = Field(description="Seniority level inferred from the posting")
    profile: str = Field(description="Legacy API label for the discovery query group")
    in_watchlist: bool = Field(default=False, description="Whether the job has been saved to the watchlist")
    skills_required: list[str] = Field(
        default_factory=list,
        description="List of required skills extracted from the posting; empty if not determinable",
    )
    score: int = Field(default=0, description="Relevance score 0-100 computed by rule-based scorer")
    score_reason: str = Field(default="", description="Short human-readable reason for the score")


class ScrapeResponse(BaseModel):
    jobs: list[JobResult] = Field(description="All jobs returned after filtering")
    total_found: int = Field(description="Total number of raw results fetched before any filtering")
    total_after_filter: int = Field(description="Number of jobs remaining after deduplication and filters")
    scraped_at: datetime = Field(description="UTC timestamp of when the scrape was executed")
    profiles_searched: list[str] = Field(description="Legacy API field containing active discovery group names")
    failed_searches: int = Field(default=0, description="Number of search attempts that raised an exception")
    hard_filter_rejections: dict[str, int] = Field(
        default_factory=dict,
        description="Counts of unique jobs rejected by each explainable hard-filter reason",
    )


__all__ = [
    "CategoryMatch",
    "FilterReason",
    "FilterResult",
    "Job",
    "JobResult",
    "ProfileMatch",
    "ScoreComponents",
    "ScrapeResponse",
]
