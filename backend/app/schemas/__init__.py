from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=5000)
    target_duration_s: int = Field(default=60, ge=30, le=600)
    style: str = "自然叙事"
    input_mode: Literal["vlog", "clips", "rough_cut", "mixed"] = "vlog"


class ProjectPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    intent: str | None = Field(default=None, min_length=1, max_length=5000)
    target_duration_s: int | None = Field(default=None, ge=30, le=600)
    style: str | None = None
    primary_asset_id: str | None = None
    input_mode: Literal["vlog", "clips", "rough_cut", "mixed"] | None = None


class VlogRecommendation(StrictModel):
    kind: Literal["reshoot", "reedit"]
    instruction: str = Field(min_length=1, max_length=400)
    shot_scale: str = Field(max_length=60)
    subject_action: str = Field(min_length=1, max_length=200)
    duration_s: float = Field(gt=0, le=30)
    insert_position: Literal["before", "after", "replace"]
    acceptance_checks: list[str] = Field(min_length=1, max_length=3)


class VlogFinding(StrictModel):
    kind: Literal["missing_context", "missing_action", "missing_result", "transition", "redundant"]
    title: str = Field(min_length=1, max_length=80)
    observation: str = Field(min_length=1, max_length=400)
    impact: str = Field(min_length=1, max_length=250)
    missing_information: str = Field(min_length=1, max_length=250)
    anchor_shot_id: str
    related_shot_id: str | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    priority: Literal["should", "optional"] = "should"
    confidence: Literal["high", "medium", "low"]
    audio_dependent: bool = False
    recommendation: VlogRecommendation


class VlogChapter(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    shot_ids: list[str] = Field(min_length=1)
    summary: str = Field(max_length=300)


class VlogReviewOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=600)
    vlog_type: str = Field(min_length=1, max_length=80)
    chapters: list[VlogChapter] = Field(default_factory=list, max_length=6)
    findings: list[VlogFinding] = Field(default_factory=list, max_length=5)


class RequirementDraft(StrictModel):
    description: str
    priority: Literal["must", "should", "optional"] = "must"
    origin: Literal["user_explicit", "model_suggested"] = "model_suggested"
    accepted_evidence_types: list[str] = Field(default_factory=lambda: ["visual"])
    dependencies: list[str] = Field(default_factory=list)
    user_confirmed: bool = False


class RequirementsOutput(StrictModel):
    requirements: list[RequirementDraft]


class EvidenceDraft(StrictModel):
    source_start_s: float = Field(ge=0)
    source_end_s: float = Field(gt=0)
    subjects: list[str] = Field(default_factory=list)
    action: str
    start_state: str = "unknown"
    end_state: str = "unknown"
    story_roles: list[str] = Field(default_factory=list)
    quality_issues: list[str] = Field(default_factory=list)
    uncertainty: str = ""
    evidence_type: Literal["visual", "audio", "text"] = "visual"


class EvidenceOutput(StrictModel):
    evidence: list[EvidenceDraft] = Field(max_length=2)


class MatchDraft(StrictModel):
    requirement_id: str
    evidence_ids: list[str]
    semantic_match: Literal["related", "unrelated", "uncertain"]
    sufficiency: Literal["supported", "partial", "not_found", "uncertain"]
    usability: Literal["usable", "limited", "unusable", "unknown"]
    reason: str
    alternative_edit: str = ""
    continuity_issue: str = ""


class MatchOutput(StrictModel):
    matches: list[MatchDraft]


class CheckResult(StrictModel):
    check: str
    status: Literal["passed", "partial", "failed", "uncertain"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationOutput(StrictModel):
    checks: list[CheckResult]
    requirement_status: Literal["passed", "partial", "failed", "uncertain"]
    reason: str
    continuity_issues: list[str] = Field(default_factory=list)


class RequirementPatch(StrictModel):
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: Literal["must", "should", "optional"] | None = None
    user_confirmed: bool | None = None


class GapPatch(StrictModel):
    status: Literal["confirmed", "dismissed", "needs_review"]
    reason: str = Field(default="", max_length=2000)


class PlanCreate(StrictModel):
    analysis_id: str
    budget_min: int | None = Field(default=None, ge=0, le=600)


class SubmissionCreate(StrictModel):
    asset_id: str


class EDLClip(StrictModel):
    asset_id: str
    source_in_s: float = Field(ge=0)
    source_out_s: float = Field(gt=0)


class EditCreate(StrictModel):
    analysis_id: str
    timeline: list[EDLClip] | None = None
    allow_reedit: bool = False
