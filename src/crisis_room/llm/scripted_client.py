from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from crisis_room.llm.contracts import LLMCallRecord, LLMClient, LLMRequest, ResponseModelT
from crisis_room.llm.task_contracts import (
    AARSummary,
    AdvisorResponse,
    EventCandidate,
    FactionDecision,
    IntentCompilation,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    PublicBrief,
)


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
    if response_model is AdvisorResponse:
        return _advisor_response(context)
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
    if response_model is InternationalPressure:
        return _international_pressure(context)
    if response_model is EventCandidate:
        return _event_candidate(context)
    if response_model is PublicBrief:
        return _public_brief(context)
    if response_model is AARSummary:
        return _aar_summary(context)
    return {}


def _advisor_response(context: dict[str, Any]) -> dict[str, Any]:
    player_message = _player_message(context)
    inbox_count = len(context.get("inbox", []))
    public_summary = _latest_public_summary(context)
    suggested = _suggested_action_ids(context, player_message)
    return {
        "answer": (
            f"Current public read: {public_summary} "
            f"You have {inbox_count} recent inbox item(s). "
            "EXCOMM can support a public demand, a naval quarantine, continued "
            "reconnaissance, or a private Kremlin channel. The key question is "
            "whether pressure leaves Moscow a way to retreat without humiliation."
        ),
        "advisor_views": [
            {
                "advisor_name": "State",
                "stance": "preserve a face-saving off-ramp",
                "reasoning": (
                    "A private Kremlin channel can test non-invasion and Jupiter "
                    "terms without making either side negotiate under cameras."
                ),
                "confidence": 0.72,
            },
            {
                "advisor_name": "Defense",
                "stance": "make pressure credible but bounded",
                "reasoning": (
                    "A quarantine is slower than an air strike, but it keeps the "
                    "President in control while showing the missiles cannot stay."
                ),
                "confidence": 0.64,
            },
            {
                "advisor_name": "CIA",
                "stance": "watch readiness and local command risk",
                "reasoning": (
                    "Reconnaissance is necessary, but every overflight also creates "
                    "a shootdown or misread pathway."
                ),
                "confidence": 0.68,
            },
        ],
        "risk_warnings": [
            "Public demands can narrow bargaining space if Moscow has no private exit.",
            "Military moves can trigger local Cuban or Soviet reactions before leaders respond.",
        ],
        "suggested_action_ids": suggested,
        "information_gaps": [
            "Whether all missile sites are operational remains uncertain.",
            "Moscow's minimum face-saving price is still inferred rather than confirmed.",
        ],
        "visible_context_limits": [
            "This advice uses only public, player-local, and inbox information.",
        ],
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
        return {
            "accepted": True,
            "action_id": "secret_jupiter_trade",
            "target_ids": ["soviet_presidium"],
            "channel": "backchannel",
            "intent_summary": "Privately float a deniable Jupiter missile understanding.",
            "private_rationale": "Offer Moscow a face-saving exit while keeping the trade out of public view.",
            "commitment_level": 0.55,
            "risk_acceptance": 0.5,
            "fallback_condition": "Deny a formal trade if the channel leaks.",
            "notes": ["Mapped player intent to the secret Jupiter trade catalog action."],
        }
    if any(token in text for token in ["non-invasion", "non invasion", "pledge", "guarantee"]):
        return {
            "accepted": True,
            "action_id": "offer_non_invasion_pledge",
            "target_ids": ["soviet_presidium", "cuba"],
            "channel": "private_diplomatic",
            "intent_summary": "Offer a private non-invasion pledge if offensive missiles are removed.",
            "private_rationale": "Reduce Cuban invasion fear and give Moscow a defendable settlement.",
            "commitment_level": 0.6,
            "risk_acceptance": 0.35,
            "notes": ["Mapped player intent to the non-invasion pledge catalog action."],
        }
    if any(token in text for token in ["air strike", "airstrike", "strike", "bomb", "invasion"]):
        return {
            "accepted": True,
            "action_id": "prepare_air_strike",
            "target_ids": ["soviet_presidium", "cuba"],
            "channel": "military",
            "intent_summary": "Prepare air strike options against missile sites in Cuba.",
            "private_rationale": "Keep a coercive option ready if missiles become operational.",
            "commitment_level": 0.85,
            "risk_acceptance": 0.8,
            "notes": ["Mapped player intent to the air strike preparation catalog action."],
        }
    if any(token in text for token in ["defcon", "readiness", "alert", "strategic"]):
        return {
            "accepted": True,
            "action_id": "raise_defcon_readiness",
            "target_ids": ["soviet_presidium"],
            "channel": "military",
            "intent_summary": "Raise strategic readiness to signal that escalation is being watched.",
            "private_rationale": "Deter a Soviet probe while preparing for rapid movement.",
            "commitment_level": 0.75,
            "risk_acceptance": 0.68,
            "notes": ["Mapped player intent to the strategic readiness catalog action."],
        }
    if any(token in text for token in ["recon", "u-2", "u2", "surveillance", "overflight"]):
        return {
            "accepted": True,
            "action_id": "authorize_recon_overflights",
            "target_ids": ["cuba"],
            "channel": "intel",
            "intent_summary": "Authorize additional reconnaissance overflights to track missile readiness.",
            "private_rationale": "Clarify site readiness before choosing irreversible military action.",
            "commitment_level": 0.55,
            "risk_acceptance": 0.45,
            "notes": ["Mapped player intent to the reconnaissance catalog action."],
        }
    if any(token in text for token in ["quarantine", "blockade", "fleet", "naval"]):
        return {
            "accepted": True,
            "action_id": "announce_quarantine",
            "target_ids": ["soviet_presidium", "cuba"],
            "channel": "public",
            "intent_summary": "Announce and prepare a naval quarantine of Cuba.",
            "public_rationale": "The United States will quarantine further offensive military shipments to Cuba.",
            "private_rationale": "Create bounded pressure while preserving room for a private settlement.",
            "commitment_level": 0.72,
            "risk_acceptance": 0.65,
            "notes": ["Mapped player intent to the naval quarantine catalog action."],
        }
    if any(token in text for token in ["public", "warn", "warning", "announce", "statement", "declare"]):
        return {
            "accepted": True,
            "action_id": "public_demand_withdrawal",
            "target_ids": [target_id],
            "channel": "public",
            "intent_summary": "Publicly demand removal of Soviet offensive missiles from Cuba.",
            "public_rationale": "Offensive missile bases in Cuba must be dismantled and removed.",
            "private_rationale": "Use public clarity to anchor allied and domestic support.",
            "commitment_level": 0.65,
            "risk_acceptance": 0.55,
            "notes": ["Mapped player intent to the public demand catalog action."],
        }
    return {
        "accepted": True,
        "action_id": "private_kremlin_backchannel",
        "target_ids": ["soviet_presidium"],
        "channel": "backchannel",
        "intent_summary": "Open a quiet Kremlin channel to explore missile withdrawal terms.",
        "private_rationale": "Test an off-ramp without forcing public concessions.",
        "commitment_level": 0.45,
        "risk_acceptance": 0.3,
        "notes": ["Mapped player intent to the private Kremlin backchannel catalog action."],
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

    action_ids = _action_ids_for_player_text(lowered)
    if not action_ids:
        action_ids = ["private_kremlin_backchannel"]

    candidates = [
        _candidate_for_scripted_action(context, action_id, source_text=text)
        for action_id in action_ids[:3]
    ]
    rejected_intents: list[str] = []
    if len(action_ids) > 3:
        rejected_intents.append(
            "Additional requested actions exceeded the three-item agenda budget."
        )
    return {
        "accepted": bool(candidates),
        "candidates": candidates,
        "rejected_intents": rejected_intents,
        "errors": [],
        "notes": ["Scripted compiler mapped player text into agenda candidates."],
    }


def _candidate_for_scripted_action(
    context: dict[str, Any],
    action_id: str,
    *,
    source_text: str,
) -> dict[str, Any]:
    trigger = {
        "secret_jupiter_trade": "jupiter",
        "offer_non_invasion_pledge": "non-invasion pledge",
        "prepare_air_strike": "air strike",
        "raise_defcon_readiness": "defcon readiness",
        "authorize_recon_overflights": "recon overflights",
        "announce_quarantine": "naval quarantine",
        "public_demand_withdrawal": "public demand withdrawal",
        "private_kremlin_backchannel": "backchannel",
    }[action_id]
    candidate_context = dict(context)
    candidate_context["player_message"] = trigger
    candidate = _intent_compilation(candidate_context)
    candidate["source_span"] = source_text[:180]
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
        preferred_action = _default_action_for_actor(actor_id, actor_type, cautious=cautious)
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
                "preferred_action_id": preferred_action,
                "target_entity_ids": [_preferred_target(context, actor_id, preferred_action)],
                "perceived_risk": 0.35 if cautious else 0.68,
                "confidence": 0.62,
            }
        )
    if not positions:
        positions.append(
            {
                "narrative_id": "institutional_default",
                "argument": "Default staff view: preserve channels while avoiding irreversible movement.",
                "preferred_action_id": _default_action_for_actor(actor_id, actor_type, cautious=True),
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
    action_id = _default_action_for_actor(actor_id, actor_type, cautious=True)
    required_resource = _resource_for_scripted_action(action_id)
    resource_value = resources.get(required_resource, 0)
    target_id = _preferred_target(context, actor_id, action_id)
    if isinstance(resource_value, int | float) and resource_value < 1:
        return {
            "action_id": None,
            "intent_summary": "",
            "no_action_reason": f"Insufficient {required_resource} for a credible catalog action.",
            "confidence": 0.65,
        }
    if action_id == "soviet_probe_compromise":
        return {
            "action_id": action_id,
            "target_ids": [target_id],
            "channel": "backchannel",
            "intent_summary": "Privately ask whether non-invasion and reciprocal restraint can settle the crisis.",
            "private_rationale": "A deniable probe protects Soviet prestige while testing a settlement.",
            "commitment_level": 0.5,
            "risk_acceptance": 0.35,
            "fallback_condition": "If Washington rejects the probe, resume public defiance.",
            "confidence": 0.68,
        }
    if action_id == "cuban_air_defense_alert":
        return {
            "action_id": action_id,
            "target_ids": [target_id],
            "channel": "military",
            "intent_summary": "Raise Cuban air defense alert in response to invasion fears.",
            "private_rationale": "Signal that Cuba will resist attack and must not be ignored in talks.",
            "commitment_level": 0.7,
            "risk_acceptance": 0.62,
            "fallback_condition": "If Moscow reins in local posture, keep alert below public panic.",
            "confidence": 0.64,
        }
    if action_id == "nato_reassurance_request":
        return {
            "action_id": action_id,
            "target_ids": [target_id],
            "channel": "private_diplomatic",
            "intent_summary": "Privately ask Washington for consultation and reassurance before the next public move.",
            "private_rationale": "Alliance support is easier to sustain when allies are not surprised.",
            "commitment_level": 0.45,
            "risk_acceptance": 0.25,
            "fallback_condition": "If ignored, reduce public enthusiasm without breaking solidarity.",
            "confidence": 0.7,
        }
    return {
        "action_id": "private_kremlin_backchannel",
        "target_ids": [target_id],
        "channel": "backchannel",
        "intent_summary": "Privately test whether reciprocal restraint is still available.",
        "private_rationale": "A deniable probe preserves face while reducing accident risk.",
        "commitment_level": 0.45,
        "risk_acceptance": 0.35,
        "fallback_condition": "If the channel leaks, deny any concession while keeping talks open.",
        "confidence": 0.68,
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
        "reason_to_include": "Accidents, ambiguous signals, and local initiative should keep pressure alive.",
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


def _suggested_action_ids(context: dict[str, Any], player_message: str) -> list[str]:
    lowered = player_message.lower()
    if any(token in lowered for token in ["jupiter", "turkey", "trade", "swap"]):
        return ["secret_jupiter_trade", "private_kremlin_backchannel"]
    if any(token in lowered for token in ["pledge", "guarantee", "non-invasion", "non invasion"]):
        return ["offer_non_invasion_pledge", "private_kremlin_backchannel"]
    if any(token in lowered for token in ["quarantine", "military", "blockade", "naval"]):
        return ["announce_quarantine", "private_kremlin_backchannel"]
    if any(token in lowered for token in ["recon", "u-2", "u2", "surveillance"]):
        return ["authorize_recon_overflights", "private_kremlin_backchannel"]
    if any(token in lowered for token in ["public", "warn", "announce"]):
        return ["public_demand_withdrawal", "private_kremlin_backchannel"]
    return ["private_kremlin_backchannel", "announce_quarantine", "offer_non_invasion_pledge"]


def _action_ids_for_player_text(lowered_text: str) -> list[str]:
    token_groups = {
        "secret_jupiter_trade": ["jupiter", "turkey", "missile trade", "swap", "trade"],
        "offer_non_invasion_pledge": [
            "non-invasion",
            "non invasion",
            "pledge",
            "guarantee",
        ],
        "prepare_air_strike": ["air strike", "airstrike", "strike", "bomb", "invasion"],
        "raise_defcon_readiness": ["defcon", "readiness", "strategic alert"],
        "authorize_recon_overflights": [
            "recon",
            "u-2",
            "u2",
            "surveillance",
            "overflight",
        ],
        "announce_quarantine": ["quarantine", "blockade", "fleet", "naval"],
        "public_demand_withdrawal": [
            "public demand",
            "demand",
            "warn",
            "warning",
            "statement",
            "declare",
        ],
        "private_kremlin_backchannel": [
            "backchannel",
            "kremlin channel",
            "quiet channel",
            "private channel",
            "dobrynin",
        ],
    }
    matches: list[tuple[int, str]] = []
    for action_id, tokens in token_groups.items():
        positions = [lowered_text.find(token) for token in tokens if token in lowered_text]
        if positions:
            matches.append((min(position for position in positions if position >= 0), action_id))
    matches.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _, action_id in matches:
        if action_id not in ordered:
            ordered.append(action_id)
    return ordered


def _preferred_target(
    context: dict[str, Any],
    actor_id: str,
    action_id: str | None = None,
) -> str:
    if action_id in {"soviet_probe_compromise", "nato_reassurance_request"}:
        return _first_profile_id(context.get("actor_public_profiles", []), actor_id, "player_faction") or "us_excomm"
    if action_id == "cuban_air_defense_alert":
        return _first_profile_id(context.get("actor_public_profiles", []), actor_id, "player_faction") or "us_excomm"
    if actor_id == "us_excomm":
        if action_id == "authorize_recon_overflights":
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


def _default_action_for_actor(
    actor_id: str,
    actor_type: str,
    *,
    cautious: bool,
) -> str:
    if actor_id == "soviet_presidium":
        return "soviet_probe_compromise" if cautious else "soviet_public_defiance"
    if actor_id == "cuba":
        return "cuban_air_defense_alert"
    if actor_id == "nato_allies":
        return "nato_reassurance_request"
    if actor_type == "opposing_faction":
        return "soviet_probe_compromise" if cautious else "soviet_public_defiance"
    if actor_type == "allied_faction":
        return "nato_reassurance_request"
    return "private_kremlin_backchannel" if cautious else "public_demand_withdrawal"


def _resource_for_scripted_action(action_id: str) -> str:
    return {
        "soviet_probe_compromise": "diplomatic_flexibility",
        "cuban_air_defense_alert": "air_defense_control",
        "nato_reassurance_request": "alliance_credit",
    }.get(action_id, "political_capital")


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
