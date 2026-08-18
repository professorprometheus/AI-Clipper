from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator


class ImportedTranscriptSegment(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def valid_window(self) -> ImportedTranscriptSegment:
        if self.end_ms <= self.start_ms:
            raise ValueError("transcript end_ms must be greater than start_ms")
        return self


class SourceInput(BaseModel):
    type: Literal["youtube_video", "youtube_playlist", "uploaded", "other"]
    url: HttpUrl
    title: str | None = None
    transcript: str | None = Field(default=None, max_length=500_000)
    transcript_segments: list[ImportedTranscriptSegment] = Field(default_factory=list)


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


class RequirementUpdate(BaseModel):
    value: Any
    reason: str = Field(min_length=3, max_length=1000)
    operator: Literal["eq", "min", "max", "contains", "present"] | None = None
    severity: Literal["mandatory", "warning"] | None = None
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


AssetType = Literal[
    "music", "meme_image", "meme_video", "reaction", "broll", "sfx", "image", "graphic"
]


class EnrichmentControls(BaseModel):
    music_allowed: bool = False
    memes_allowed: bool = False
    broll_allowed: bool = False
    sound_effects_allowed: bool = False
    external_images_allowed: bool = False
    external_video_allowed: bool = False
    required_asset_source: str | None = Field(default=None, max_length=500)
    prohibited_asset_types: list[AssetType] = Field(default_factory=list)
    max_inserts: int = Field(default=3, ge=0, le=20)
    max_insert_duration_seconds: float = Field(default=2.0, gt=0, le=30)
    music_volume_min_db: float = Field(default=-30.0, ge=-60, le=0)
    music_volume_max_db: float = Field(default=-12.0, ge=-60, le=0)
    ducking_required: bool = True
    additional_instructions: str = Field(default="", max_length=10_000)

    @model_validator(mode="after")
    def valid_volume_range(self) -> EnrichmentControls:
        if self.music_volume_min_db > self.music_volume_max_db:
            raise ValueError("music volume minimum must not exceed maximum")
        return self


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: EmailStr
    platform: str = "Content Rewards"
    campaign_url: HttpUrl | None = None
    payout_model: str | None = "qualified_view_block"
    payout_amount: float | None = Field(default=0, ge=0)
    views_per_payout_unit: int | None = Field(default=1000, gt=0)
    payout_rules: dict[str, Any] = Field(default_factory=dict)
    payout_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    deadline: str | None = None
    research_seeds: list[str] = Field(default_factory=list, max_length=100)
    target_platforms: list[str] = Field(default_factory=lambda: ["manual_export"])
    target_account_ids: list[str] = Field(default_factory=list, max_length=100)
    sources: list[SourceInput] = Field(default_factory=list, max_length=500)
    successful_examples: list[ExampleInput] = Field(default_factory=list, max_length=500)
    requirements: list[RequirementInput] = Field(default_factory=list, max_length=200)
    watermark: WatermarkInput | None = None
    raw_brief: str = Field(default="", max_length=100_000)
    enrichment: EnrichmentControls = Field(default_factory=EnrichmentControls)

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

    @model_validator(mode="after")
    def normalize_legacy_payout(self) -> CampaignCreate:
        legacy_only = (
            "payout_value" in self.model_fields_set and "payout_amount" not in self.model_fields_set
        )
        if legacy_only and self.payout_value is not None:
            self.payout_amount = self.payout_value
            if "payout_model" not in self.model_fields_set:
                self.payout_model = "per_qualified_view"
                self.views_per_payout_unit = 1
        if self.payout_model == "per_qualified_view" and self.views_per_payout_unit == 1000:
            self.views_per_payout_unit = 1
        return self


class PastedSourceTranscriptInput(BaseModel):
    transcript: str | None = Field(default=None, max_length=500_000)
    segments: list[ImportedTranscriptSegment] = Field(default_factory=list)

    @model_validator(mode="after")
    def has_content(self) -> PastedSourceTranscriptInput:
        if not (self.transcript or "").strip() and not self.segments:
            raise ValueError("paste transcript text or timestamped segments")
        return self


class ReviewInput(BaseModel):
    decision: Literal["approve", "change", "reject"]
    reason_code: (
        Literal[
            "bad_moment",
            "weak_hook",
            "bad_editing",
            "wrong_topic",
            "too_much_context",
            "captions",
            "crop",
            "missed_requirement",
            "overdone_saturated",
            "other",
        ]
        | None
    ) = None
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
    reason_code: (
        Literal[
            "bad_moment",
            "weak_hook",
            "bad_editing",
            "wrong_topic",
            "too_much_context",
            "captions",
            "crop",
            "missed_requirement",
            "overdone_saturated",
            "market_outperformed_preference",
            "preference_outperformed_market",
            "other",
        ]
        | None
    ) = None
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


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1000)


class ConnectedAccountCreate(BaseModel):
    platform: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    adapter: Literal["manual_export"] = "manual_export"


class ResearchObservationInput(BaseModel):
    platform: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    creator: str = Field(min_length=1, max_length=300)
    published_hours_ago: float = Field(ge=0)
    metrics: dict[str, float | int]
    creator_baseline: dict[str, float | int]
    transcript: str = Field(min_length=1, max_length=100_000)
    labels: dict[str, str]
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def research_fields(self) -> ResearchObservationInput:
        if "views" not in self.metrics:
            raise ValueError("research metrics require views")
        if "median_views" not in self.creator_baseline:
            raise ValueError("creator baseline requires median_views")
        if not self.labels.get("topic") or not self.labels.get("angle"):
            raise ValueError("research labels require topic and angle")
        return self


class ResearchImportBatch(BaseModel):
    provenance: str = Field(min_length=5, max_length=2000)
    observations: list[ResearchObservationInput] = Field(min_length=1, max_length=5000)
