from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CategoryMatch(BaseModel):
    name: str
    similarity: float


class ProfileMatch(BaseModel):
    name: str
    similarity: float


class ScoreComponent(BaseModel):
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    matched_signals: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def score_does_not_exceed_maximum(self):
        if self.score > self.max_score:
            raise ValueError("component score must not exceed max_score")
        return self


class PreScoreResult(BaseModel):
    total: float = Field(ge=0, le=100)
    seniority: ScoreComponent
    technologies: ScoreComponent
    role: ScoreComponent
    location: ScoreComponent

    @model_validator(mode="after")
    def total_matches_components(self):
        components = (self.seniority, self.technologies, self.role, self.location)
        if abs(sum(component.max_score for component in components) - 100) > 1e-6:
            raise ValueError("pre-score component maxima must sum to 100")
        if abs(sum(component.score for component in components) - self.total) > 1e-6:
            raise ValueError("pre-score total must equal the component scores")
        return self


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
    pre_score_components: PreScoreResult | None = None
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
    pre_score: float | None = Field(default=None, description="Explainable deterministic score from 0 to 100")
    pre_score_components: PreScoreResult | None = Field(
        default=None,
        description="Stored components and evidence used to calculate the pre-score",
    )
    score: int = Field(default=0, description="Legacy n8n-compatible alias of the rounded pre-score")
    score_reason: str = Field(default="", description="Legacy n8n-compatible pre-score component summary")


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
    "PreScoreResult",
    "ProfileMatch",
    "ScoreComponent",
    "ScrapeResponse",
]
