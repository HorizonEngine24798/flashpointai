from __future__ import annotations

from enum import Enum

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crisis_room.state.signals import PayloadType, SignalChannel, SignalVisibility


class CrisisEventKind(str, Enum):
    HISTORICAL = "historical"
    CHAOS = "chaos"
    INSTITUTIONAL_FRICTION = "institutional_friction"
    LOCAL_INITIATIVE = "local_initiative"
    MEDIA_LEAK = "media_leak"


_NUMERIC_FIELD_NAMES = {
    "confidence",
    "perceived_risk",
    "commitment_level",
    "trust_player_delta",
    "paranoia_delta",
    "urgency_delta",
    "institutional_confidence_delta",
    "trust_delta",
    "leak_risk_delta",
    "relationship_delta",
    "reliability",
    "leak_risk",
    "distortion_risk",
    "urgency",
    "plausibility",
    "escalation_pressure",
}
_NUMERIC_MAP_FIELD_NAMES = {
    "trust_channel_deltas",
    "belief_value_deltas",
    "deterministic_effect_hints",
}
_BOOLEAN_FIELD_NAMES = {
    "accepted",
}


class LLMContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _reject_hidden_scalar_coercion(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        for key, value in raw.items():
            if key in _NUMERIC_FIELD_NAMES:
                _require_json_number(key, value)
            elif key in _BOOLEAN_FIELD_NAMES and not isinstance(value, bool):
                raise ValueError(f"{key} must be a JSON boolean")
            elif key in _NUMERIC_MAP_FIELD_NAMES:
                _require_json_number_map(key, value)
        return raw


class BeliefUpdate(LLMContractModel):
    topic: str
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_signal_ids: list[str] = Field(default_factory=list)


class PerceptionUpdate(LLMContractModel):
    situation_summary: str
    belief_updates: list[BeliefUpdate] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    memory_notes: list[str] = Field(default_factory=list)
    priority_questions: list[str] = Field(default_factory=list)


class NarrativePosition(LLMContractModel):
    narrative_id: str
    argument: str
    preferred_action_id: str | None = None
    preferred_capability_id: str | None = None
    target_entity_ids: list[str] = Field(default_factory=list)
    perceived_risk: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class InternalDebate(LLMContractModel):
    positions: list[NarrativePosition] = Field(default_factory=list)
    synthesis: str
    dominant_narrative_id: str | None = None
    unresolved_disagreements: list[str] = Field(default_factory=list)


class FactionDecision(LLMContractModel):
    action_id: str | None = None
    capability_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str = ""
    public_rationale: str = ""
    private_rationale: str = ""
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    parameters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    no_action_reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class FactionTurnResponse(LLMContractModel):
    perception_update: PerceptionUpdate
    internal_debate: InternalDebate
    decision: FactionDecision
    self_critique: list[str] = Field(default_factory=list, max_length=6)


class AdvisorView(LLMContractModel):
    advisor_id: str
    advisor_name: str
    stance: str
    reasoning: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AdvisorDeltaProposal(LLMContractModel):
    advisor_id: str
    trust_player_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    paranoia_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    urgency_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    institutional_confidence_delta: float = Field(default=0.0, ge=-1.0, le=1.0)
    trust_channel_deltas: dict[str, float] = Field(default_factory=dict)
    belief_value_deltas: dict[str, float] = Field(default_factory=dict)
    belief_summaries: dict[str, str] = Field(default_factory=dict)
    memory_notes: list[str] = Field(default_factory=list, max_length=4)
    recommendation_notes: list[str] = Field(default_factory=list, max_length=4)
    embarrassment_notes: list[str] = Field(default_factory=list, max_length=4)
    reasons: list[str] = Field(default_factory=list, max_length=4)


class AdvisorCouncilResponse(LLMContractModel):
    answer: str
    council_summary: str = ""
    advisor_views: list[AdvisorView] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    suggested_capability_ids: list[str] = Field(default_factory=list)
    suggested_action_ids: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    visible_context_limits: list[str] = Field(default_factory=list)
    proposed_advisor_deltas: list[AdvisorDeltaProposal] = Field(default_factory=list)


class BackchannelCounterpartResponse(LLMContractModel):
    response_text: str = Field(min_length=1, max_length=500)
    trust_delta: float = Field(default=0.0, ge=-0.12, le=0.12)
    leak_risk_delta: float = Field(default=0.0, ge=-0.05, le=0.12)
    relationship_delta: float = Field(default=0.0, ge=-0.12, le=0.12)


class BackchannelStateChange(LLMContractModel):
    memory_note: str = Field(default="", max_length=400)
    unresolved_thread: str = Field(default="", max_length=160)
    belief_updates: list[BeliefUpdate] = Field(default_factory=list, max_length=4)


class SignalDistortionResponse(LLMContractModel):
    observed_content: str = Field(min_length=1, max_length=700)
    distortion_note: str = Field(default="", max_length=240)


class IntentCompilationCandidate(LLMContractModel):
    accepted: bool
    action_id: str | None = None
    capability_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str = ""
    public_rationale: str = ""
    private_rationale: str = ""
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    parameters: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    source_span: str = ""
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MultiIntentCompilation(LLMContractModel):
    accepted: bool
    candidates: list[IntentCompilationCandidate] = Field(default_factory=list)
    rejected_intents: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_single_candidate_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        values = dict(raw)
        if "candidates" not in values and (
            "action_id" in values or "intent_summary" in values or "target_ids" in values
        ):
            candidate = {
                "accepted": values.get("accepted", False),
                "action_id": values.get("action_id"),
                "capability_id": values.get("capability_id"),
                "target_ids": values.get("target_ids", []),
                "channel": values.get("channel", SignalChannel.PRIVATE_DIPLOMATIC),
                "intent_summary": values.get("intent_summary", ""),
                "public_rationale": values.get("public_rationale", ""),
                "private_rationale": values.get("private_rationale", ""),
                "commitment_level": values.get("commitment_level", 0.5),
                "parameters": values.get("parameters", {}),
                "errors": values.get("errors", []),
                "notes": values.get("notes", []),
            }
            values["candidates"] = [candidate] if candidate["accepted"] else []
            values["rejected_intents"] = values.get("rejected_intents", [])
            values["errors"] = values.get("errors", [])
            values["notes"] = values.get("notes", [])
            for key in [
                "action_id",
                "capability_id",
                "target_ids",
                "channel",
                "intent_summary",
                "public_rationale",
                "private_rationale",
                "commitment_level",
                "parameters",
            ]:
                values.pop(key, None)
        return values


class SignalCandidate(LLMContractModel):
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


class EventCandidate(LLMContractModel):
    candidate_id: str
    kind: CrisisEventKind
    title: str
    summary: str
    plausibility: float = Field(default=0.5, ge=0.0, le=1.0)
    escalation_pressure: float = Field(default=0.5, ge=0.0, le=1.0)
    target_entity_ids: list[str] = Field(default_factory=list)
    suggested_signals: list[SignalCandidate] = Field(default_factory=list)
    deterministic_effect_hints: dict[str, float] = Field(default_factory=dict)


class InternationalPressure(LLMContractModel):
    situation_summary: str
    pressure_signals: list[SignalCandidate] = Field(default_factory=list)


class PublicBrief(LLMContractModel):
    headline: str
    summary: str
    public_risk_read: str = ""


class EventCreatorResponse(LLMContractModel):
    public_brief: PublicBrief
    event_candidate: EventCandidate | None = None


def _require_json_number(field_name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a JSON number")


def _require_json_number_map(field_name: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object of JSON numbers")
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_name} keys must be strings")
        _require_json_number(f"{field_name}.{key}", item)
