from __future__ import annotations

from enum import Enum

from typing import Any

from pydantic import BaseModel, Field, model_validator

from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility


class CrisisEventKind(str, Enum):
    HISTORICAL = "historical"
    CHAOS = "chaos"
    INSTITUTIONAL_FRICTION = "institutional_friction"
    LOCAL_INITIATIVE = "local_initiative"
    MEDIA_LEAK = "media_leak"


class BeliefUpdate(BaseModel):
    topic: str
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_signal_ids: list[str] = Field(default_factory=list)


class PerceptionUpdate(BaseModel):
    situation_summary: str
    belief_updates: list[BeliefUpdate] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    priority_questions: list[str] = Field(default_factory=list)


class NarrativePosition(BaseModel):
    narrative_id: str
    argument: str
    preferred_action_id: str | None = None
    target_entity_ids: list[str] = Field(default_factory=list)
    perceived_risk: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class InternalDebate(BaseModel):
    positions: list[NarrativePosition] = Field(default_factory=list)
    synthesis: str
    dominant_narrative_id: str | None = None
    unresolved_disagreements: list[str] = Field(default_factory=list)


class FactionDecision(BaseModel):
    action_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str = ""
    public_rationale: str = ""
    private_rationale: str = ""
    requested_timing: str = "current_turn"
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_acceptance: float = Field(default=0.5, ge=0.0, le=1.0)
    fallback_condition: str | None = None
    no_action_reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AdvisorView(BaseModel):
    advisor_name: str
    stance: str
    reasoning: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AdvisorResponse(BaseModel):
    answer: str
    advisor_views: list[AdvisorView] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    suggested_action_ids: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    visible_context_limits: list[str] = Field(default_factory=list)


class IntentCompilation(BaseModel):
    accepted: bool
    action_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str = ""
    public_rationale: str = ""
    private_rationale: str = ""
    requested_timing: str = "current_turn"
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_acceptance: float = Field(default=0.5, ge=0.0, le=1.0)
    fallback_condition: str | None = None
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class IntentCompilationCandidate(BaseModel):
    accepted: bool
    action_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str = ""
    public_rationale: str = ""
    private_rationale: str = ""
    requested_timing: str = "current_turn"
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    risk_acceptance: float = Field(default=0.5, ge=0.0, le=1.0)
    fallback_condition: str | None = None
    source_span: str = ""
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MultiIntentCompilation(BaseModel):
    accepted: bool
    candidates: list[IntentCompilationCandidate] = Field(default_factory=list, max_length=3)
    rejected_intents: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_single_intent(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        values = dict(raw)
        if "candidates" not in values and (
            "action_id" in values or "intent_summary" in values or "target_ids" in values
        ):
            candidate = {
                "accepted": values.get("accepted", False),
                "action_id": values.get("action_id"),
                "target_ids": values.get("target_ids", []),
                "channel": values.get("channel", SignalChannel.PRIVATE_DIPLOMATIC),
                "intent_summary": values.get("intent_summary", ""),
                "public_rationale": values.get("public_rationale", ""),
                "private_rationale": values.get("private_rationale", ""),
                "requested_timing": values.get("requested_timing", "current_turn"),
                "commitment_level": values.get("commitment_level", 0.5),
                "risk_acceptance": values.get("risk_acceptance", 0.5),
                "fallback_condition": values.get("fallback_condition"),
                "errors": values.get("errors", []),
                "notes": values.get("notes", []),
            }
            values["candidates"] = [candidate] if candidate["accepted"] else []
            values["rejected_intents"] = values.get("rejected_intents", [])
            values["errors"] = values.get("errors", [])
            values["notes"] = values.get("notes", [])
        candidates = values.get("candidates")
        if isinstance(candidates, list) and len(candidates) > 3:
            values["candidates"] = candidates[:3]
            notes = list(values.get("notes") or [])
            notes.append("Compiler returned more than three candidates; extra intents were ignored.")
            values["notes"] = notes
        return values


class SignalCandidate(BaseModel):
    target_entity_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PUBLIC
    payload_type: PayloadType = PayloadType.PUBLIC_STATEMENT
    content: str
    visibility: SignalVisibility = SignalVisibility.PUBLIC
    reliability: float = Field(default=0.75, ge=0.0, le=1.0)
    leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    distortion_risk: float = Field(default=0.1, ge=0.0, le=1.0)
    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    classification: str = "unclassified"


class EventCandidate(BaseModel):
    candidate_id: str
    kind: CrisisEventKind
    title: str
    summary: str
    plausibility: float = Field(default=0.5, ge=0.0, le=1.0)
    escalation_pressure: float = Field(default=0.5, ge=0.0, le=1.0)
    target_entity_ids: list[str] = Field(default_factory=list)
    suggested_signals: list[SignalCandidate] = Field(default_factory=list)
    deterministic_effect_hints: dict[str, float] = Field(default_factory=dict)
    reason_to_include: str = ""


class InternationalPressure(BaseModel):
    situation_summary: str
    legitimacy_concerns: list[str] = Field(default_factory=list)
    requested_restraints: list[str] = Field(default_factory=list)
    pressure_signals: list[SignalCandidate] = Field(default_factory=list)
    escalation_read: float = Field(default=0.5, ge=0.0, le=1.0)


class PublicBrief(BaseModel):
    headline: str
    summary: str
    public_risk_read: str = ""
    safe_known_facts: list[str] = Field(default_factory=list)
    public_uncertainties: list[str] = Field(default_factory=list)
    omitted_private_topics: list[str] = Field(default_factory=list)


class AARTurningPoint(BaseModel):
    turn: int = Field(ge=0)
    title: str
    causal_summary: str
    visible_at_the_time: bool = False


class AARSummary(BaseModel):
    outcome_summary: str
    turning_points: list[AARTurningPoint] = Field(default_factory=list)
    causal_factors: list[str] = Field(default_factory=list)
    missed_offramps: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
