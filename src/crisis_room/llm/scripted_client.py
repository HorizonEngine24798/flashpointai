from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from crisis_room.config.gameplay import SCRIPTED_SOURCE_SPAN_LIMIT
from crisis_room.llm.contracts import LLMCallRecord, LLMClient, LLMRequest, ResponseModelT
from crisis_room.llm.task_contracts import (
    AARSummary,
    AdvisorCouncilResponse,
    AdvisorResponse,
    BackchannelAvailabilityCheck,
    BackchannelCounterpartResponse,
    BackchannelStateChange,
    EventCandidate,
    EventCreatorResponse,
    FactionDecision,
    FactionTurnResponse,
    IntentCompilation,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    PublicBrief,
    SignalDistortionResponse,
)


SCRIPTED_CAPABILITY_ACTIONS = {
    "cuba_open_kremlin_channel": "private_diplomacy",
    "cuba_direct_kremlin_message": "backchannel_message",
    "cuba_public_withdrawal_demand": "public_statement",
    "cuba_announce_naval_quarantine": "military_posture",
    "cuba_recon_overflights": "reconnaissance",
    "cuba_raise_defcon_readiness": "military_posture",
    "cuba_offer_non_invasion_pledge": "private_diplomacy",
    "cuba_secret_jupiter_trade": "private_diplomacy",
    "cuba_prepare_air_strike": "military_posture",
    "soviet_compromise_probe": "private_diplomacy",
    "soviet_defiance_statement": "public_statement",
    "cuba_air_defense_alert": "military_posture",
    "nato_reassurance_pressure": "private_diplomacy",
}


class ScriptedLLMClient(LLMClient):
    """Deterministic typed-response client for playable local debug sessions."""

    def __init__(self) -> None:
        self.calls: list[LLMCallRecord] = []

    def complete_json(
        self,
        request: LLMRequest,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        context = _extract_visible_context(request)
        raw = _scripted_response(request, response_model, context)
        record = LLMCallRecord(request=request, raw_response=raw)
        try:
            response = response_model.model_validate(raw)
        except Exception as exc:
            record.validation_error = str(exc)
            self.calls.append(record)
            raise
        record.parsed_response = response.model_dump(mode="json")
        self.calls.append(record)
        return response


def _scripted_response(
    request: LLMRequest,
    response_model: type[BaseModel],
    context: dict[str, Any],
) -> dict[str, Any]:
    if response_model in {AdvisorCouncilResponse, AdvisorResponse}:
        return _advisor_response(context)
    if response_model is BackchannelAvailabilityCheck:
        return _backchannel_availability_check(context)
    if response_model is BackchannelCounterpartResponse:
        return _backchannel_counterpart_response(context)
    if response_model is BackchannelStateChange:
        return _backchannel_state_change(context)
    if response_model is IntentCompilation:
        return _intent_compilation(context)
    if response_model is MultiIntentCompilation:
        return _multi_intent_compilation(context)
    if response_model is PerceptionUpdate:
        return _perception_update(context)
    if response_model is InternalDebate:
        return _internal_debate(context)
    if response_model is FactionDecision:
        return _faction_decision(context)
    if response_model is FactionTurnResponse:
        return _faction_turn_response(context)
    if response_model is InternationalPressure:
        return _international_pressure(context)
    if response_model is EventCandidate:
        return _event_candidate(context)
    if response_model is EventCreatorResponse:
        return _event_creator_response(context)
    if response_model is PublicBrief:
        return _public_brief(context)
    if response_model is SignalDistortionResponse:
        return _signal_distortion_response(context)
    if response_model is AARSummary:
        return _aar_summary(context)
    return {}


def _advisor_response(context: dict[str, Any]) -> dict[str, Any]:
    player_message = _player_message(context)
    inbox_count = len(context.get("inbox", []))
    public_summary = _latest_public_summary(context)
    advisor_entries = _advisor_entries(context)
    suggested_capabilities = _suggested_capability_ids(context, player_message)
    suggested_actions = _action_ids_for_capabilities(suggested_capabilities)
    state = _advisor_entry(advisor_entries, "state")
    defense = _advisor_entry(advisor_entries, "defense")
    intelligence = _advisor_entry(advisor_entries, "intelligence")
    state_memory = _advisor_memory_clause(state)
    defense_trust = _inter_advisor_trust(defense, "state")
    intelligence_embarrassment = _advisor_embarrassment_clause(intelligence)
    defense_reasoning = (
        "A quarantine is slower than an air strike, but it keeps the President "
        "in control while showing the missiles cannot stay."
    )
    if defense_trust >= 0.65:
        defense_reasoning = (
            "Defense can live with State's off-ramp if military pressure remains "
            "credible and tightly bounded."
        )
    elif defense_trust and defense_trust < 0.45:
        defense_reasoning = (
            "Defense is not convinced State's channel will hold; any private probe "
            "needs visible pressure behind it."
        )
    return {
        "answer": (
            f"Current public read: {public_summary} "
            f"You have {inbox_count} recent inbox item(s). "
            "EXCOMM can support a public demand, a naval quarantine, continued "
            "reconnaissance, or a private Kremlin channel. The key question is "
            "whether pressure leaves Moscow a way to retreat without humiliation."
        ),
        "council_summary": (
            "The room leans toward pressure with an off-ramp, but disagrees over "
            "how much public commitment to add before the private channel is tested."
        ),
        "advisor_views": [
            {
                "advisor_id": "state",
                "advisor_name": _advisor_name(state, "State"),
                "stance": "preserve a face-saving off-ramp",
                "reasoning": (
                    "A private Kremlin channel can test non-invasion and Jupiter "
                    f"terms without making either side negotiate under cameras.{state_memory}"
                ),
                "confidence": 0.72,
            },
            {
                "advisor_id": "defense",
                "advisor_name": _advisor_name(defense, "Defense"),
                "stance": "make pressure credible but bounded",
                "reasoning": defense_reasoning,
                "confidence": 0.64,
            },
            {
                "advisor_id": "intelligence",
                "advisor_name": _advisor_name(intelligence, "CIA"),
                "stance": "watch readiness and local command risk",
                "reasoning": (
                    "Reconnaissance is necessary, but every overflight also creates "
                    f"a shootdown or misread pathway.{intelligence_embarrassment}"
                ),
                "confidence": 0.68,
            },
        ],
        "risk_warnings": [
            "Public demands can narrow bargaining space if Moscow has no private exit.",
            "Military moves can trigger local Cuban or Soviet reactions before leaders respond.",
        ],
        "suggested_capability_ids": suggested_capabilities,
        "suggested_action_ids": suggested_actions,
        "information_gaps": [
            "Whether all missile sites are operational remains uncertain.",
            "Moscow's minimum face-saving price is still inferred rather than confirmed.",
        ],
        "visible_context_limits": [
            "This advice uses only public, player-local, and inbox information.",
        ],
        "proposed_advisor_deltas": _advisor_delta_proposals(player_message),
    }


def _advisor_entries(context: dict[str, Any]) -> list[dict[str, Any]]:
    council = context.get("advisor_council", {})
    if not isinstance(council, dict):
        return []
    advisors = council.get("advisors", [])
    return [advisor for advisor in advisors if isinstance(advisor, dict)]


def _advisor_entry(entries: list[dict[str, Any]], advisor_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry.get("advisor_id") == advisor_id:
            return entry
    return {"advisor_id": advisor_id, "name": advisor_id.replace("_", " ").title()}


def _advisor_name(entry: dict[str, Any], fallback: str) -> str:
    name = entry.get("name")
    return str(name) if name else fallback


def _advisor_memory_clause(entry: dict[str, Any]) -> str:
    recommendations = entry.get("recent_recommendations")
    if isinstance(recommendations, list) and recommendations:
        return f" Their last recommendation still matters: {recommendations[-1]}"
    memory = entry.get("memory_summary")
    if isinstance(memory, str) and memory.strip():
        return f" They remember: {memory.strip()}"
    return ""


def _advisor_embarrassment_clause(entry: dict[str, Any]) -> str:
    embarrassments = entry.get("recent_embarrassments")
    if isinstance(embarrassments, list) and embarrassments:
        return f" After the last embarrassment, hedge the confidence: {embarrassments[-1]}"
    return ""


def _inter_advisor_trust(entry: dict[str, Any], other_advisor_id: str) -> float:
    trust = entry.get("trust_advisors", {})
    if not isinstance(trust, dict):
        return 0.0
    value = trust.get(other_advisor_id, 0.0)
    return float(value) if isinstance(value, int | float) else 0.0


def _advisor_delta_proposals(player_message: str) -> list[dict[str, Any]]:
    lowered = player_message.lower()
    if any(token in lowered for token in ["off-ramp", "off ramp", "least escalatory"]):
        return [
            {
                "advisor_id": "state",
                "trust_player_delta": 0.02,
                "urgency_delta": -0.01,
                "memory_notes": ["The player asked for advice that preserved an off-ramp."],
                "recommendation_notes": [
                    "Pair public pressure with a concrete private settlement formula."
                ],
                "reasons": ["Player sought a controlled diplomatic path."],
            }
        ]
    if any(token in lowered for token in ["strike", "bomb", "invasion"]):
        return [
            {
                "advisor_id": "defense",
                "urgency_delta": 0.025,
                "paranoia_delta": 0.015,
                "recommendation_notes": ["Clarify command authority before strike planning."],
                "reasons": ["Player asked about a highly escalatory military option."],
            }
        ]
    return []


def _backchannel_counterpart_response(context: dict[str, Any]) -> dict[str, Any]:
    message = _player_message(context)
    lowered = message.lower()
    if any(token in lowered for token in ["ultimatum", "threat", "strike", "bomb", "invasion"]):
        return {
            "accepted": True,
            "response_text": (
                "Threats in this channel will harden public positions. If Washington "
                "wants a settlement, send concrete reciprocal terms."
            ),
            "stance": "wary",
            "trust_delta": -0.06,
            "leak_risk_delta": 0.03,
            "relationship_delta": -0.04,
            "notes": ["Threatening language narrows the off-ramp."],
        }
    if any(token in lowered for token in ["jupiter", "turkey", "trade", "swap"]):
        return {
            "accepted": True,
            "response_text": (
                "Any Turkey/Jupiter understanding must remain deniable and separate "
                "from the public withdrawal formula."
            ),
            "stance": "interested",
            "trust_delta": 0.03,
            "leak_risk_delta": 0.05,
            "relationship_delta": 0.02,
            "notes": ["Secret trade language raises leak exposure."],
        }
    if any(token in lowered for token in ["non-invasion", "non invasion", "pledge", "guarantee"]):
        return {
            "accepted": True,
            "response_text": (
                "A private non-invasion assurance could move Moscow if it is paired "
                "with a face-saving public path for missile removal."
            ),
            "stance": "constructive",
            "trust_delta": 0.04,
            "leak_risk_delta": 0.01,
            "relationship_delta": 0.03,
            "notes": ["Constructive reciprocal language keeps the channel useful."],
        }
    return {
        "accepted": True,
        "response_text": (
            "The message is noted. Moscow needs a more specific settlement formula "
            "before changing its public position."
        ),
        "stance": "cautious",
        "trust_delta": 0.0,
        "leak_risk_delta": 0.0,
        "relationship_delta": 0.0,
        "notes": [],
    }


def _backchannel_availability_check(context: dict[str, Any]) -> dict[str, Any]:
    extra = context.get("extra", {})
    target_query = ""
    if isinstance(extra, dict):
        target_query = str(extra.get("backchannel_target_query", ""))
    query = target_query.strip().lower().replace("_", " ")
    profiles = context.get("actor_public_profiles", [])
    if isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            entity_id = str(profile.get("entity_id", ""))
            name = str(profile.get("name", ""))
            candidates = {
                entity_id.lower().replace("_", " "),
                name.lower().replace("_", " "),
            }
            if query in candidates or any(candidate.startswith(query) for candidate in candidates):
                return {
                    "allowed": True,
                    "available": True,
                    "target_entity_id": entity_id,
                    "target_label": name or entity_id,
                    "reason": "Target maps to a scenario actor with gamestate.",
                    "confidence": 0.9,
                }
    return {
        "allowed": True,
        "available": False,
        "target_entity_id": "",
        "target_label": target_query,
        "reason": "Target has no scenario actor gamestate.",
        "confidence": 0.8,
    }


def _backchannel_state_change(context: dict[str, Any]) -> dict[str, Any]:
    message = _player_message(context)
    lowered = message.lower()
    if any(token in lowered for token in ["ultimatum", "threat", "strike", "bomb", "invasion"]):
        return {
            "memory_note": "The backchannel carried threatening language and narrowed trust.",
            "unresolved_thread": "Assess whether Washington is using the channel for coercion.",
            "belief_updates": [
                {
                    "topic": "backchannel_pressure",
                    "summary": "The private channel may be turning coercive rather than exploratory.",
                    "confidence": 0.62,
                }
            ],
            "trust_delta": -0.04,
            "leak_risk_delta": 0.03,
            "relationship_delta": -0.04,
            "notes": ["Threatening backchannel language reduces confidence."],
        }
    if any(token in lowered for token in ["jupiter", "turkey", "trade", "swap"]):
        return {
            "memory_note": "The exchange raised a deniable Jupiter/Turkey trade possibility.",
            "unresolved_thread": "Keep any missile-trade discussion separate from public terms.",
            "belief_updates": [
                {
                    "topic": "private_trade_possible",
                    "summary": "A quiet reciprocal concession may be available if deniable.",
                    "confidence": 0.58,
                }
            ],
            "trust_delta": 0.02,
            "leak_risk_delta": 0.04,
            "relationship_delta": 0.02,
            "notes": ["Secret trade talk is useful but leak-prone."],
        }
    if any(token in lowered for token in ["non-invasion", "non invasion", "pledge", "guarantee"]):
        return {
            "memory_note": "The exchange made a private non-invasion assurance more salient.",
            "unresolved_thread": "Test whether public missile withdrawal can be paired with private assurances.",
            "belief_updates": [
                {
                    "topic": "non_invasion_offramp",
                    "summary": "A private non-invasion assurance could support a face-saving withdrawal path.",
                    "confidence": 0.64,
                }
            ],
            "trust_delta": 0.03,
            "leak_risk_delta": 0.01,
            "relationship_delta": 0.03,
            "notes": ["Constructive settlement language preserves the channel."],
        }
    return {
        "memory_note": "The backchannel exchange was cautious and did not settle concrete terms.",
        "unresolved_thread": "Ask for a more specific settlement formula before changing posture.",
        "belief_updates": [],
        "trust_delta": 0.0,
        "leak_risk_delta": 0.0,
        "relationship_delta": 0.0,
        "notes": [],
    }


def _intent_compilation(context: dict[str, Any]) -> dict[str, Any]:
    text = _player_message(context).lower()
    actor_id = str(context.get("entity", {}).get("entity_id", "us_excomm"))
    target_id = _preferred_target(context, actor_id)
    if any(token in text for token in ["hold", "wait", "no action", "stand down", "end turn"]):
        return {
            "accepted": False,
            "errors": [],
            "notes": ["Player chose to hold formal action this turn."],
        }
    if any(token in text for token in ["jupiter", "turkey", "missile trade", "swap", "trade"]):
        return _accepted_intent(
            "cuba_secret_jupiter_trade",
            target_ids=["soviet_presidium"],
            channel="backchannel",
            intent_summary="Privately float a deniable Jupiter missile understanding.",
            private_rationale="Offer Moscow a face-saving exit while keeping the trade out of public view.",
            commitment_level=0.55,
            risk_acceptance=0.5,
            fallback_condition="Deny a formal trade if the channel leaks.",
            notes=["Mapped player intent to the secret Jupiter trade capability."],
        )
    if any(token in text for token in ["non-invasion", "non invasion", "pledge", "guarantee"]):
        return _accepted_intent(
            "cuba_offer_non_invasion_pledge",
            target_ids=["soviet_presidium", "cuba"],
            channel="private_diplomatic",
            intent_summary="Offer a private non-invasion pledge if offensive missiles are removed.",
            private_rationale="Reduce Cuban invasion fear and give Moscow a defendable settlement.",
            commitment_level=0.6,
            risk_acceptance=0.35,
            notes=["Mapped player intent to the non-invasion pledge capability."],
        )
    if any(token in text for token in ["air strike", "airstrike", "strike", "bomb", "invasion"]):
        return _accepted_intent(
            "cuba_prepare_air_strike",
            target_ids=["soviet_presidium", "cuba"],
            channel="military",
            intent_summary="Prepare air strike options against missile sites in Cuba.",
            private_rationale="Keep a coercive option ready if missiles become operational.",
            commitment_level=0.85,
            risk_acceptance=0.8,
            notes=["Mapped player intent to the air strike preparation capability."],
        )
    if any(token in text for token in ["defcon", "readiness", "alert", "strategic"]):
        return _accepted_intent(
            "cuba_raise_defcon_readiness",
            target_ids=["soviet_presidium"],
            channel="military",
            intent_summary="Raise strategic readiness to signal that escalation is being watched.",
            private_rationale="Deter a Soviet probe while preparing for rapid movement.",
            commitment_level=0.75,
            risk_acceptance=0.68,
            notes=["Mapped player intent to the strategic readiness capability."],
        )
    if any(token in text for token in ["recon", "u-2", "u2", "surveillance", "overflight"]):
        return _accepted_intent(
            "cuba_recon_overflights",
            target_ids=["cuba"],
            channel="intel",
            intent_summary="Authorize additional reconnaissance overflights to track missile readiness.",
            private_rationale="Clarify site readiness before choosing irreversible military action.",
            commitment_level=0.55,
            risk_acceptance=0.45,
            notes=["Mapped player intent to the reconnaissance capability."],
        )
    if any(token in text for token in ["quarantine", "blockade", "fleet", "naval"]):
        return _accepted_intent(
            "cuba_announce_naval_quarantine",
            target_ids=["soviet_presidium", "cuba"],
            channel="public",
            intent_summary="Announce and prepare a naval quarantine of Cuba.",
            public_rationale="The United States will quarantine further offensive military shipments to Cuba.",
            private_rationale="Create bounded pressure while preserving room for a private settlement.",
            commitment_level=0.72,
            risk_acceptance=0.65,
            notes=["Mapped player intent to the naval quarantine capability."],
        )
    if any(token in text for token in ["public", "warn", "warning", "announce", "statement", "declare"]):
        return _accepted_intent(
            "cuba_public_withdrawal_demand",
            target_ids=[target_id],
            channel="public",
            intent_summary="Publicly demand removal of Soviet offensive missiles from Cuba.",
            public_rationale="Offensive missile bases in Cuba must be dismantled and removed.",
            private_rationale="Use public clarity to anchor allied and domestic support.",
            commitment_level=0.65,
            risk_acceptance=0.55,
            notes=["Mapped player intent to the public demand capability."],
        )
    return _accepted_intent(
        "cuba_open_kremlin_channel",
        target_ids=["soviet_presidium"],
        channel="backchannel",
        intent_summary="Open a quiet Kremlin channel to explore missile withdrawal terms.",
        private_rationale="Test an off-ramp without forcing public concessions.",
        commitment_level=0.45,
        risk_acceptance=0.3,
        notes=["Mapped player intent to the private Kremlin channel capability."],
    )


def _accepted_intent(
    capability_id: str,
    *,
    target_ids: list[str],
    channel: str,
    intent_summary: str,
    public_rationale: str = "",
    private_rationale: str = "",
    commitment_level: float = 0.5,
    risk_acceptance: float = 0.5,
    fallback_condition: str | None = None,
    parameters: dict[str, Any] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "accepted": True,
        "action_id": SCRIPTED_CAPABILITY_ACTIONS[capability_id],
        "capability_id": capability_id,
        "target_ids": target_ids,
        "channel": channel,
        "intent_summary": intent_summary,
        "public_rationale": public_rationale,
        "private_rationale": private_rationale,
        "commitment_level": commitment_level,
        "risk_acceptance": risk_acceptance,
        "fallback_condition": fallback_condition,
        "parameters": parameters or {},
        "notes": notes or [],
    }


def _multi_intent_compilation(context: dict[str, Any]) -> dict[str, Any]:
    text = _player_message(context)
    lowered = text.lower()
    if any(token in lowered for token in ["hold", "wait", "no action", "stand down", "end turn"]):
        return {
            "accepted": False,
            "candidates": [],
            "errors": [],
            "notes": ["Player chose to hold formal action this turn."],
        }

    capability_ids = _capability_ids_for_player_text(lowered)
    if not capability_ids:
        capability_ids = ["cuba_open_kremlin_channel"]

    candidates = [
        _candidate_for_scripted_capability(context, capability_id, source_text=text)
        for capability_id in capability_ids
    ]
    return {
        "accepted": bool(candidates),
        "candidates": candidates,
        "rejected_intents": [],
        "errors": [],
        "notes": ["Scripted compiler mapped player text into agenda candidates."],
    }


def _candidate_for_scripted_capability(
    context: dict[str, Any],
    capability_id: str,
    *,
    source_text: str,
) -> dict[str, Any]:
    trigger = {
        "cuba_secret_jupiter_trade": "jupiter",
        "cuba_direct_kremlin_message": source_text,
        "cuba_offer_non_invasion_pledge": "non-invasion pledge",
        "cuba_prepare_air_strike": "air strike",
        "cuba_raise_defcon_readiness": "defcon readiness",
        "cuba_recon_overflights": "recon overflights",
        "cuba_announce_naval_quarantine": "naval quarantine",
        "cuba_public_withdrawal_demand": "public demand withdrawal",
        "cuba_open_kremlin_channel": "backchannel",
    }[capability_id]
    candidate_context = dict(context)
    candidate_context["player_message"] = trigger
    candidate = _intent_compilation(candidate_context)
    if capability_id == "cuba_direct_kremlin_message":
        candidate["parameters"] = {"message_text": source_text}
    candidate["source_span"] = source_text[:SCRIPTED_SOURCE_SPAN_LIMIT]
    return candidate


def _perception_update(context: dict[str, Any]) -> dict[str, Any]:
    entity = context.get("entity", {})
    name = str(entity.get("name", "The faction"))
    inbox = context.get("inbox", [])
    public_summary = _latest_public_summary(context)
    source_ids = [
        str(item.get("signal_id"))
        for item in inbox
        if isinstance(item, dict) and item.get("signal_id")
    ]
    return {
        "situation_summary": (
            f"{name} reads the Cuba crisis as unstable. Public signal: {public_summary} "
            f"Recent inbox volume: {len(inbox)}."
        ),
        "belief_updates": [
            {
                "topic": "opponent_posture",
                "summary": "The opponent is testing resolve, but a face-saving off-ramp may still exist.",
                "confidence": 0.58,
                "source_signal_ids": source_ids,
            }
        ],
        "uncertainty_notes": [
            "Channel distortion may hide the other side's true willingness to compromise."
        ],
        "memory_notes": ["Escalation pressure is easier to create than to unwind."],
        "priority_questions": ["Can restraint be made credible without appearing weak?"],
    }


def _internal_debate(context: dict[str, Any]) -> dict[str, Any]:
    actor_id = str(context.get("entity", {}).get("entity_id", ""))
    actor_type = str(context.get("entity", {}).get("entity_type", ""))
    narratives = context.get("entity", {}).get("internal_narratives", [])
    positions: list[dict[str, Any]] = []
    for narrative in narratives or []:
        if not isinstance(narrative, dict):
            continue
        narrative_id = str(narrative.get("narrative_id", "narrative"))
        name = str(narrative.get("name", narrative_id))
        worldview = str(narrative.get("worldview", ""))
        cautious = any(
            token in f"{narrative_id} {name} {worldview}".lower()
            for token in ["exit", "restraint", "diplomatic", "settlement", "bargain", "risk"]
        )
        preferred_capability = _default_capability_for_actor(
            actor_id,
            actor_type,
            cautious=cautious,
        )
        positions.append(
            {
                "narrative_id": narrative_id,
                "argument": (
                    f"{name}: "
                    + (
                        "probe a deniable off-ramp before public commitments harden."
                        if cautious
                        else "maintain credible pressure so the opponent cannot pocket delay."
                    )
                ),
                "preferred_action_id": SCRIPTED_CAPABILITY_ACTIONS[preferred_capability],
                "preferred_capability_id": preferred_capability,
                "target_entity_ids": [_preferred_target(context, actor_id, preferred_capability)],
                "perceived_risk": 0.35 if cautious else 0.68,
                "confidence": 0.62,
            }
        )
    if not positions:
        positions.append(
            {
                "narrative_id": "institutional_default",
                "argument": "Default staff view: preserve channels while avoiding irreversible movement.",
                "preferred_action_id": SCRIPTED_CAPABILITY_ACTIONS[
                    _default_capability_for_actor(actor_id, actor_type, cautious=True)
                ],
                "preferred_capability_id": _default_capability_for_actor(
                    actor_id,
                    actor_type,
                    cautious=True,
                ),
                "target_entity_ids": [_preferred_target(context, actor_id)],
                "perceived_risk": 0.45,
                "confidence": 0.55,
            }
        )
    return {
        "positions": positions,
        "synthesis": "The faction favors a controlled signal with a private escape route.",
        "dominant_narrative_id": positions[-1]["narrative_id"],
        "unresolved_disagreements": [
            "How much public pressure can be added before it becomes self-binding?"
        ],
    }


def _faction_decision(context: dict[str, Any]) -> dict[str, Any]:
    entity = context.get("entity", {})
    actor_id = str(entity.get("entity_id", "actor"))
    actor_type = str(entity.get("entity_type", ""))
    resources = entity.get("resources", {})
    if not isinstance(resources, dict):
        resources = {}
    capability_id = _default_capability_for_actor(actor_id, actor_type, cautious=True)
    action_id = SCRIPTED_CAPABILITY_ACTIONS[capability_id]
    required_resource = _resource_for_scripted_capability(capability_id)
    resource_value = resources.get(required_resource, 0)
    target_id = _preferred_target(context, actor_id, capability_id)
    if isinstance(resource_value, int | float) and resource_value < 1:
        return {
            "action_id": None,
            "capability_id": None,
            "intent_summary": "",
            "no_action_reason": f"Insufficient {required_resource} for a credible catalog action.",
            "confidence": 0.65,
        }
    if capability_id == "soviet_compromise_probe":
        return {
            "action_id": action_id,
            "capability_id": capability_id,
            "target_ids": [target_id],
            "channel": "backchannel",
            "intent_summary": "Privately ask whether non-invasion and reciprocal restraint can settle the crisis.",
            "private_rationale": "A deniable probe protects Soviet prestige while testing a settlement.",
            "commitment_level": 0.5,
            "risk_acceptance": 0.35,
            "fallback_condition": "If Washington rejects the probe, resume public defiance.",
            "parameters": {},
            "confidence": 0.68,
        }
    if capability_id == "cuba_air_defense_alert":
        return {
            "action_id": action_id,
            "capability_id": capability_id,
            "target_ids": [target_id],
            "channel": "military",
            "intent_summary": "Raise Cuban air defense alert in response to invasion fears.",
            "private_rationale": "Signal that Cuba will resist attack and must not be ignored in talks.",
            "commitment_level": 0.7,
            "risk_acceptance": 0.62,
            "fallback_condition": "If Moscow reins in local posture, keep alert below public panic.",
            "parameters": {},
            "confidence": 0.64,
        }
    if capability_id == "nato_reassurance_pressure":
        return {
            "action_id": action_id,
            "capability_id": capability_id,
            "target_ids": [target_id],
            "channel": "private_diplomatic",
            "intent_summary": "Privately ask Washington for consultation and reassurance before the next public move.",
            "private_rationale": "Alliance support is easier to sustain when allies are not surprised.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.25,
            "fallback_condition": "If ignored, reduce public enthusiasm without breaking solidarity.",
            "parameters": {},
            "confidence": 0.7,
        }
    capability_id = "cuba_open_kremlin_channel"
    return {
        "action_id": SCRIPTED_CAPABILITY_ACTIONS[capability_id],
        "capability_id": capability_id,
        "target_ids": [target_id],
        "channel": "backchannel",
        "intent_summary": "Privately test whether reciprocal restraint is still available.",
        "private_rationale": "A deniable probe preserves face while reducing accident risk.",
        "commitment_level": 0.45,
        "risk_acceptance": 0.35,
        "fallback_condition": "If the channel leaks, deny any concession while keeping talks open.",
        "parameters": {},
        "confidence": 0.68,
    }


def _faction_turn_response(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "perception_update": _perception_update(context),
        "internal_debate": _internal_debate(context),
        "decision": _faction_decision(context),
        "self_critique": [
            "The final choice preserves optionality, but visible signals may still be misread.",
            "The faction is inferring rival intent from incomplete public and inbox context.",
        ],
    }


def _international_pressure(context: dict[str, Any]) -> dict[str, Any]:
    public_summary = _latest_public_summary(context)
    return {
        "situation_summary": f"External actors see a widening Cuba crisis: {public_summary}",
        "legitimacy_concerns": [
            "A quarantine needs legal and regional legitimacy to avoid looking like a blockade.",
            "Military preparations sharpen humanitarian, market, and nuclear anxiety.",
        ],
        "requested_restraints": [
            "Keep a channel open through the UN, OAS, or a private intermediary.",
            "Avoid air strikes while ships, aircraft, and local commanders are in close contact.",
        ],
        "pressure_signals": [
            {
                "channel": "media",
                "payload_type": "media_report",
                "content": "International diplomats and media outlets call for restraint over Cuba.",
                "visibility": "public",
                "reliability": 0.82,
                "urgency": 0.6,
            }
        ],
        "escalation_read": 0.62,
    }


def _event_candidate(context: dict[str, Any]) -> dict[str, Any]:
    turn = int(context.get("turn_number", 1))
    if turn % 3 == 0:
        return {
            "candidate_id": f"allied_pressure_{turn}",
            "kind": "historical",
            "title": "Allied Consultation Pressure",
            "summary": "An allied capital asks whether Washington will consult before any public missile trade.",
            "plausibility": 0.7,
            "escalation_pressure": 0.45,
            "suggested_signals": [
                {
                    "target_entity_ids": ["us_excomm"],
                    "channel": "private_diplomatic",
                    "payload_type": "private_diplomatic_message",
                    "content": "An allied government privately asks for consultation and reassurance.",
                    "visibility": "private",
                    "reliability": 0.78,
                }
            ],
            "deterministic_effect_hints": {"allied_confidence": -0.02},
            "reason_to_include": "Allied pressure complicates any secret Jupiter or public quarantine package.",
        }
    return {
        "candidate_id": f"recon_confusion_{turn}",
        "kind": "chaos",
        "title": "Reconnaissance Confusion",
        "summary": "Local air defense and naval reports misread routine movement as possible attack preparation.",
        "plausibility": 0.63,
        "escalation_pressure": 0.7,
            "suggested_signals": [
                {
                    "target_entity_ids": ["us_excomm"],
                    "channel": "intel",
                "payload_type": "intel_report",
                "content": "Intercepts suggest confused Cuban and Soviet local traffic around reconnaissance activity.",
                "visibility": "secret",
                "reliability": 0.55,
                "urgency": 0.7,
                }
            ],
            "deterministic_effect_hints": {
                "command_and_control_risk": 0.02,
                "public_alarm": 0.01,
            },
            "reason_to_include": "Accidents, ambiguous signals, and local initiative should keep pressure alive.",
        }


def _event_creator_response(context: dict[str, Any]) -> dict[str, Any]:
    candidate = _event_candidate(context)
    public_brief = _public_brief(context)
    public_brief["headline"] = candidate["title"]
    public_brief["summary"] = candidate["summary"]
    return {
        "public_brief": public_brief,
        "event_candidate": candidate,
        "major_event_relevant": True,
        "editorial_notes": [
            "Public-facing coverage emphasizes visible crisis pressure and omits private channels.",
            "A major event candidate remains subject to deterministic approval.",
        ],
    }


def _public_brief(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "headline": "Crisis Diplomacy Continues",
        "summary": _latest_public_summary(context),
        "public_risk_read": "Public alarm remains elevated.",
        "safe_known_facts": [_latest_public_summary(context)],
        "public_uncertainties": ["Private diplomatic positions remain unclear."],
        "omitted_private_topics": ["Inbox reports and hidden clocks are not public facts."],
    }


def _signal_distortion_response(context: dict[str, Any]) -> dict[str, Any]:
    original = str(context.get("original_content", "A report is unclear."))
    kind = str(context.get("kind", "distorted"))
    if kind == "contradictory":
        content = f"Sources disagree on the report; one reading claims {original}"
    else:
        content = f"Channel noise blurs the report: {original}"
    return {
        "observed_content": content,
        "distortion_note": "Scripted info-channel distortion.",
    }


def _aar_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "outcome_summary": "The debug session ended with the crisis still active.",
        "turning_points": [],
        "causal_factors": [
            "Public pressure, private channels, and event pressure interacted across turns."
        ],
        "missed_offramps": [],
        "uncertainty_notes": ["This scripted summary is deterministic and non-omniscient."],
    }


def _extract_visible_context(request: LLMRequest) -> dict[str, Any]:
    for message in request.messages:
        marker = "Visible context JSON:\n"
        if marker not in message.content:
            continue
        start = message.content.index(marker) + len(marker)
        end_marker = "\n\nTask:\n"
        end = message.content.find(end_marker, start)
        raw_json = message.content[start:] if end == -1 else message.content[start:end]
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _player_message(context: dict[str, Any]) -> str:
    value = context.get("player_message", "")
    return value if isinstance(value, str) else ""


def _latest_public_summary(context: dict[str, Any]) -> str:
    timeline = context.get("public_timeline", [])
    if isinstance(timeline, list) and timeline:
        latest = timeline[-1]
        if isinstance(latest, dict):
            return str(latest.get("summary", "No public summary is available."))
    return "No public summary is available."


def _suggested_capability_ids(context: dict[str, Any], player_message: str) -> list[str]:
    lowered = player_message.lower()
    if any(token in lowered for token in ["jupiter", "turkey", "trade", "swap"]):
        return ["cuba_secret_jupiter_trade", "cuba_open_kremlin_channel"]
    if any(token in lowered for token in ["pledge", "guarantee", "non-invasion", "non invasion"]):
        return ["cuba_offer_non_invasion_pledge", "cuba_open_kremlin_channel"]
    if any(token in lowered for token in ["quarantine", "military", "blockade", "naval"]):
        return ["cuba_announce_naval_quarantine", "cuba_open_kremlin_channel"]
    if any(token in lowered for token in ["recon", "u-2", "u2", "surveillance"]):
        return ["cuba_recon_overflights", "cuba_open_kremlin_channel"]
    if any(token in lowered for token in ["public", "warn", "announce"]):
        return ["cuba_public_withdrawal_demand", "cuba_open_kremlin_channel"]
    if any(token in lowered for token in ["strike", "bomb", "invasion"]):
        return ["cuba_prepare_air_strike", "cuba_open_kremlin_channel"]
    return ["cuba_open_kremlin_channel", "cuba_announce_naval_quarantine"]


def _action_ids_for_capabilities(capability_ids: list[str]) -> list[str]:
    action_ids: list[str] = []
    for capability_id in capability_ids:
        action_id = SCRIPTED_CAPABILITY_ACTIONS[capability_id]
        if action_id not in action_ids:
            action_ids.append(action_id)
    return action_ids


def _capability_ids_for_player_text(lowered_text: str) -> list[str]:
    token_groups = {
        "cuba_secret_jupiter_trade": ["jupiter", "turkey", "missile trade", "swap", "trade"],
        "cuba_offer_non_invasion_pledge": [
            "non-invasion",
            "non invasion",
            "pledge",
            "guarantee",
        ],
        "cuba_prepare_air_strike": ["air strike", "airstrike", "strike", "bomb", "invasion"],
        "cuba_raise_defcon_readiness": ["defcon", "readiness", "strategic alert"],
        "cuba_recon_overflights": [
            "recon",
            "u-2",
            "u2",
            "surveillance",
            "overflight",
        ],
        "cuba_announce_naval_quarantine": ["quarantine", "blockade", "fleet", "naval"],
        "cuba_public_withdrawal_demand": [
            "public demand",
            "demand",
            "warn",
            "warning",
            "statement",
            "declare",
        ],
        "cuba_open_kremlin_channel": [
            "backchannel",
            "kremlin channel",
            "quiet channel",
            "private channel",
            "dobrynin",
        ],
    }
    matches: list[tuple[int, str]] = []
    for capability_id, tokens in token_groups.items():
        positions = [lowered_text.find(token) for token in tokens if token in lowered_text]
        if positions:
            matches.append((min(position for position in positions if position >= 0), capability_id))
    matches.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _, capability_id in matches:
        if capability_id not in ordered:
            ordered.append(capability_id)
    return ordered


def _preferred_target(
    context: dict[str, Any],
    actor_id: str,
    capability_id: str | None = None,
) -> str:
    if capability_id in {"soviet_compromise_probe", "nato_reassurance_pressure"}:
        return _first_profile_id(context.get("actor_public_profiles", []), actor_id, "player_faction") or "us_excomm"
    if capability_id == "cuba_air_defense_alert":
        return _first_profile_id(context.get("actor_public_profiles", []), actor_id, "player_faction") or "us_excomm"
    if actor_id == "us_excomm":
        if capability_id == "cuba_recon_overflights":
            return "cuba"
        return "soviet_presidium"
    profiles = context.get("actor_public_profiles", [])
    if isinstance(profiles, list):
        opposing = _first_profile_id(profiles, actor_id, "opposing_faction")
        if opposing:
            return opposing
        player = _first_profile_id(profiles, actor_id, "player_faction")
        if player:
            return player
        for profile in profiles:
            if isinstance(profile, dict):
                entity_id = str(profile.get("entity_id", ""))
                if entity_id and entity_id != actor_id:
                    return entity_id
    return "soviet_presidium" if actor_id == "us_excomm" else "us_excomm"


def _default_capability_for_actor(
    actor_id: str,
    actor_type: str,
    *,
    cautious: bool,
) -> str:
    if actor_id == "soviet_presidium":
        return "soviet_compromise_probe" if cautious else "soviet_defiance_statement"
    if actor_id == "cuba":
        return "cuba_air_defense_alert"
    if actor_id == "nato_allies":
        return "nato_reassurance_pressure"
    if actor_type == "opposing_faction":
        return "soviet_compromise_probe" if cautious else "soviet_defiance_statement"
    if actor_type == "allied_faction":
        return "nato_reassurance_pressure"
    return "cuba_open_kremlin_channel" if cautious else "cuba_public_withdrawal_demand"


def _resource_for_scripted_capability(capability_id: str) -> str:
    return {
        "soviet_compromise_probe": "diplomatic_flexibility",
        "cuba_air_defense_alert": "air_defense_control",
        "nato_reassurance_pressure": "alliance_credit",
    }.get(capability_id, "political_capital")


def _first_profile_id(
    profiles: list[Any],
    actor_id: str,
    entity_type: str,
) -> str:
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        if profile.get("entity_type") != entity_type:
            continue
        entity_id = str(profile.get("entity_id", ""))
        if entity_id and entity_id != actor_id:
            return entity_id
    return ""
