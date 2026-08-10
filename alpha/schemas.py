from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator


class SourceInput(BaseModel):
    type: Literal["youtube_video", "youtube_playlist", "uploaded", "other"]
    url: HttpUrl
    title: str | None = None


class ExampleInput(BaseModel):
    url: HttpUrl
    platform: str = "unknown"
    creator: str | None = None


class RequirementInput(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    type: Literal["deterministic", "ai_evaluated", "informational"]
    operator: Literal["eq", "min", "max", "contains", "present"] = "eq"
    value: Any
    severity: Literal["mandatory", "warning"] = "mandatory"
    source_text: str | None = None


class WatermarkInput(BaseModel):
    data_base64: str | None = None
    filename: str = "watermark.ppm"
    position: Literal["top_left", "top_right", "bottom_left", "bottom_right", "center"] = (
        "bottom_right"
    )
    opacity: float = Field(default=0.85, ge=0.0, le=1.0)
    padding: int = Field(default=24, ge=0, le=500)
    size_pct: float = Field(default=0.18, gt=0.01, le=1.0)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    platform: str = "Content Rewards"
    campaign_url: HttpUrl | None = None
    payout_model: str | None = "per_qualified_view"
    payout_value: float | None = Field(default=0, ge=0)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    deadline: str | None = None
    research_seeds: list[str] = Field(default_factory=list, max_length=100)
    target_platforms: list[str] = Field(default_factory=lambda: ["manual_export"])
    sources: list[SourceInput] = Field(min_length=1, max_length=500)
    successful_examples: list[ExampleInput] = Field(default_factory=list, max_length=500)
    requirements: list[RequirementInput] = Field(default_factory=list, max_length=200)
    watermark: WatermarkInput | None = None

    @field_validator("currency")
    @classmethod
    def upper_currency(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def unique_urls(self) -> CampaignCreate:
        source_urls = [str(item.url).rstrip("/") for item in self.sources]
        example_urls = [str(item.url).rstrip("/") for item in self.successful_examples]
        if len(set(source_urls)) != len(source_urls):
            raise ValueError("duplicate approved source URL")
        if len(set(example_urls)) != len(example_urls):
            raise ValueError("duplicate successful example URL")
        return self


class ReviewInput(BaseModel):
    decision: Literal["approve", "change", "reject"]
    reason_code: str | None = None
    feedback_text: str | None = None

    @model_validator(mode="after")
    def require_detail(self) -> ReviewInput:
        if self.decision == "change" and not self.feedback_text:
            raise ValueError("a change request needs natural-language instructions")
        if self.decision == "reject" and not (self.reason_code or self.feedback_text):
            raise ValueError("a rejection needs a reason")
        return self


class PublishInput(BaseModel):
    platform: str = "manual_export"
    account_id: str | None = None
    caption: str = ""


class FeedbackInput(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    reason_code: str | None = None
    feedback_text: str | None = None
    human_minutes: float | None = Field(default=None, ge=0)
    clip_variant_id: str | None = None


class PerformanceInput(BaseModel):
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    qualified_views: int = Field(default=0, ge=0)
    accepted: bool | None = None
    revenue: float = Field(default=0, ge=0)
    payout: float = Field(default=0, ge=0)
    currency: str = "GBP"
    account_baseline_views: float | None = Field(default=None, ge=0)


class ExperimentInput(BaseModel):
    hypothesis: str = Field(min_length=1)
    treatment_weights: dict[str, float]
    allocation: float = Field(default=0.15, gt=0, lt=1)
