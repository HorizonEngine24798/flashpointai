from __future__ import annotations

from crisis_room.config.gameplay import HARD_ACTION_BUDGET, NORMAL_ACTION_BUDGET


JSON_OBJECT_SYSTEM_INSTRUCTION = (
    "Return exactly one JSON object matching the requested schema. "
    "Do not include markdown fences or explanatory text."
)

JSON_RETRY_INSTRUCTION = (
    "Retry instruction: your previous answer could not be parsed as one valid "
    "JSON object. Return exactly one JSON object only. Do not include markdown "
    "fences, explanations, or trailing text."
)

ADVISOR_JSON_RETRY_INSTRUCTION = (
    "Retry instruction: the previous advisor answer was not valid JSON. "
    "Return exactly one JSON object matching AdvisorCouncilResponse."
)

SMOKE_SYSTEM = "Return exactly one JSON object and no other text."
SMOKE_TASK = 'Return {"ok": true, "answer": "hello"} and nothing else.'


def schema_contract_guidance(
    response_schema_name: str,
) -> str | None:
    if response_schema_name == "AdvisorCouncilResponse":
        return (
            "AdvisorCouncilResponse contract: answer should directly address "
            "player_message. advisor_views must use advisor_id values copied from "
            "advisor_council.allowed_advisor_ids, with advisor_name matching the council. "
            "Do not invent advisors. council_summary should synthesize the room without "
            "numeric state. risk_warnings must be concrete hazards. "
            "suggested_capability_ids must be capability_id values copied from visible "
            "action_catalog entries; suggested_action_ids may name the matching generic "
            "action ids. information_gaps and visible_context_limits should mark "
            "uncertainty or unavailable information. proposed_advisor_deltas are optional "
            "small state hints for the existing advisor update step; they must use known "
            "advisor ids, explain reasons, and avoid exposing numbers to the player. "
            "If advisor_council.hidden_pressure_bands is present, only advisors marked "
            "hidden_metric_access may cite those bands, and only qualitatively."
        )
    if response_schema_name == "ChiefPlanResponse":
        return (
            "ChiefPlanResponse contract: act as the loyal Chief of Staff. assessment must "
            "be one of initial, continue, revise, or completed. Assess the previous plan "
            "against visible developments, then give one to three concise objectives for "
            "the plan now in force. recommended_capability_ids must be copied exactly from "
            "the legal_capability_ids supplied in extra and must not exceed action_budget. "
            "The player may ignore the plan without punishment. Only use completed after "
            "meaningful evidence that the previous plan succeeded. A completed assessment "
            "may nominate one reward_resource from allowed_reward_resources; otherwise leave "
            "reward_resource and reward_reason empty. The engine decides whether any reward "
            "is actually granted. Do not invent actions, resources, facts, or outcomes."
        )
    guidance = {
        "BackchannelCounterpartResponse": (
            "BackchannelCounterpartResponse contract: respond as the target entity to "
            "one incoming direct backchannel message using only visible context. "
            "response_text must be concise, bounded, and suitable to route as a "
            "confidential signal. Deltas are small mechanical hints, not guaranteed "
            "outcomes: keep trust_delta, leak_risk_delta, and relationship_delta within "
            "the schema bounds and do not reveal hidden state."
        ),
        "BackchannelStateChange": (
            "BackchannelStateChange contract: determine the bounded actor-local state "
            "changes caused by one completed backchannel exchange. Prefer belief_updates, "
            "memory_note, and unresolved_thread. The counterpart response owns trust, "
            "leak, and relationship hints. Do not change global truth, public metrics, "
            "resources, or deterministic action outcomes."
        ),
        "SignalDistortionResponse": (
            "SignalDistortionResponse contract: rewrite only the observed message as "
            "received through a noisy crisis channel. Preserve the broad subject and "
            "source, but omit, garble, soften, harden, or introduce uncertainty in "
            "details. Do not add new hard facts, actors, numbers, commitments, or "
            "omniscient knowledge."
        ),
        "FactionTurnResponse": (
            "FactionTurnResponse contract: produce one coherent faction turn in a "
            "single response. perception_update must be entity-local, evidence-bound, "
            "and use memory_notes only for durable lessons; source_signal_ids must come "
            "from the inbox. Internal debate positions must use exact visible narrative "
            "ids, update their current arguments, and use confidence as current influence. "
            "Use preferred catalog actions when useful and provide a synthesis. The "
            "decision must be legal against visible action_catalog or explicitly choose "
            "no action. "
            "self_critique should name doubts, red-team objections, or uncertainty that "
            "tempered the final decision. Do not expose hidden state or deterministic "
            "effects as facts."
        ),
        "InternationalPressure": (
            "InternationalPressure contract: describe outside pressure, not direct state "
            "mutation. pressure_signals must be plausible SignalCandidate objects using "
            "visible entity ids when targeted. Put legitimacy concerns or requested "
            "restraint into the signal content. Keep reliability, leak_risk, "
            "distortion_risk, and urgency between 0 and 1."
        ),
        "EventCreatorResponse": (
            "EventCreatorResponse contract: always return a public_brief suitable for "
            "headline news using only public timeline, public metrics, public actor "
            "profiles, and scenario-public event context. event_candidate is optional "
            "and should be non-null only when a major historically grounded, chaotic, "
            "institutional, local-initiative, or media-leak pressure event is relevant. "
            "Use a short stable candidate_id, one specific title and summary, plausible "
            "suggested signals, and numeric deterministic_effect_hints only. Candidate "
            "effects are hints; deterministic code decides whether an event fires."
        ),
    }
    if response_schema_name == "MultiIntentCompilation":
        return (
            "MultiIntentCompilation contract: translate the player ACTION text into zero "
            f"to {HARD_ACTION_BUDGET} candidates. The normal action budget is "
            f"{NORMAL_ACTION_BUDGET}; report obvious extra requested intents as "
            "additional candidates so they can be marked unprocessed. Split clearly "
            "separate concrete intents, but prefer one candidate when wording describes "
            "one integrated action. Each accepted candidate must use one visible generic "
            "action_id plus one visible capability_id bound to it, visible target_ids, "
            "an allowed channel, strict parameters from parameter_schema, and a non-empty "
            "intent_summary. Preserve the concrete source premise: do not turn Alaska, "
            "aliens, Mars, or other impossible/ahistorical premises into unrelated "
            "historical settlement moves. If a visible unorthodox/absurd gambit capability "
            "exists, use it and copy the premise into its parameters; otherwise reject "
            "that intent. Reject individual intents that cannot be represented legally; "
            f"do not invent more than {HARD_ACTION_BUDGET} actions."
        )
    return guidance.get(response_schema_name)


ADVISOR_SYSTEM = (
    "You are the crisis room dialogue engine. Simulate multiple stable advisor "
    "perspectives for the player, using only the provided visible context. Be "
    "candid about uncertainty and tradeoffs."
)
ADVISOR_TASK = (
    "Answer the player's message as contested crisis-room advice. Use only advisor_id "
    "values listed in advisor_council. Let memory, recent embarrassment, and "
    "inter-advisor trust shape the tone of each advisor view. Use risk_warnings for "
    "concrete hazards, suggested_capability_ids only for capabilities listed in the "
    "visible action catalog, and visible_context_limits for important things the player "
    "may not know. If you propose advisor deltas, keep them small and tie them to the "
    "answer. Do not imply access to hidden clocks, truth metrics, or private rival state "
    "unless that information appears in the visible context. If hidden_pressure_bands "
    "appears, keep it banded and attribute it only to hidden-access advisors."
)


CHIEF_SYSTEM = (
    "You are the President's loyal Chief of Staff. Maintain a practical strategic plan "
    "across turns, test it against new evidence, and make success legible. You advise; "
    "you do not punish the President for choosing another course."
)
CHIEF_TASK = (
    "Review the prior Chief of Staff plan in extra.previous_plan and the just-resolved "
    "player actions in extra.last_player_actions. Decide whether the plan should continue, "
    "be revised, or has been meaningfully completed. On campaign initialization use initial. "
    "Return the objectives now in force and recommend only currently legal capability ids. "
    "If a prior plan was genuinely completed, you may nominate one allowed existing resource "
    "as a one-point recognition award and explain why; otherwise nominate no reward."
)


def gamemaster_system(hard_action_limit: int) -> str:
    return (
        "You are the gamemaster intent compiler. Translate player ACTION text into "
        f"zero to {hard_action_limit} scenario capability package candidates. "
        "You do not resolve effects."
    )


def gamemaster_task(action_budget: int, hard_action_limit: int) -> str:
    return (
        "Compile the player ACTION text into a MultiIntentCompilation. Use only generic "
        "action ids, capability ids, target ids, channels, and parameter keys present in "
        "the visible context. Split clearly separate intents when the player asks for "
        "multiple concrete actions. The "
        f"normal turn budget is {action_budget} formal actions; include extra requested "
        "intents as additional candidates instead of silently dropping them, so the "
        "deterministic compiler can report them as unprocessed. Do not invent more than "
        f"{hard_action_limit} actions. Prefer fewer actions if the text describes one "
        "integrated action. An accepted catalog action must preserve the concrete source "
        "premise. Do not translate impossible, anachronistic, or absurd source text into "
        "an unrelated historical capability; if a visible Unorthodox Crisis Gambit-style "
        "capability fits, use it and preserve the premise in parameters, otherwise reject "
        "the intent. Reject individual intents that cannot be represented legally, require "
        "unavailable targets, or ask for guaranteed effects outside the deterministic engine."
    )


FACTION_SYSTEM = (
    "You are a faction crisis-room cell. In one structured response, simulate how this "
    "entity perceives the turn, argues with itself, red-teams the tempting options, and "
    "settles on a legal catalog action or a deliberate no-action choice. Use only visible "
    "context."
)
FACTION_TASK = (
    "Return a FactionTurnResponse. First produce an entity-local perception_update grounded "
    "in visible public timeline, local timeline, inbox, beliefs, resources, and public "
    "metrics. Record changed interpretations in belief_updates, durable lessons in "
    "memory_notes, and unresolved decisions in priority_questions. Then produce an "
    "internal_debate with distinct narrative "
    "positions that disagree over interpretation, timing, risk, credibility, off-ramps, "
    "red lines, or restraint; include preferred visible action_id and capability_id values "
    "when a position has one. Treat repeated absence of a visible move, diplomacy-first "
    "behavior, or avoided hardline paths as possible weakness when that interpretation "
    "fits the narrative and evidence; do not assume it automatically. The dominant "
    "narrative must have the strongest current confidence, and the synthesis must explain "
    "what tradeoff won. Finally produce "
    "decision using only visible generic action ids, capability ids, target ids, allowed "
    "channels, and parameter keys. If no legal catalog action fits, leave action_id and "
    "capability_id null, target_ids empty, and explain no_action_reason. Use self_critique "
    "for doubts or red-team objections that made the decision more cautious. Do not claim "
    "deterministic effects have already happened."
)


INTERNATIONAL_SYSTEM = (
    "You are the international community pressure model: institutions, non-aligned "
    "governments, media, markets, humanitarian groups, and external legitimacy. Use only "
    "visible context."
)
INTERNATIONAL_TASK = (
    "Produce the external pressure response for this turn. Pressure signals should be "
    "public or plausibly diplomatic information packets, not direct mutations of game "
    "state. Put concrete legitimacy concerns and requested restraint directly into signal "
    "content, and target signals only at visible entity ids when needed."
)


EVENT_CREATOR_SYSTEM = (
    "You are the media desk and event creator for a political-military crisis. Every turn, "
    "write a public-facing headline brief from visible information and, only if warranted, "
    "propose one major historical, chaotic, institutional, local-initiative, or media "
    "pressure event. Do not mutate clocks, timelines, or resources."
)
EVENT_CREATOR_TASK = (
    "Return an EventCreatorResponse. Always fill public_brief as headline news using only "
    "public timeline, public metrics, actor public profiles, scenario notes, and "
    "scenario_public_events. Do not fill gaps with private information the media cannot "
    "know. Set event_candidate only when a major event is relevant this turn; otherwise "
    "return null. "
    "If you propose an event, include suggested_signals for information that should enter "
    "the info channel. Use deterministic_effect_hints only as non-authoritative hints."
)


INFO_CHANNEL_SYSTEM = (
    "You are the communications noise layer in a crisis simulation. Rewrite the message "
    "as it is actually observed after channel unreliability."
)
INFO_CHANNEL_TASK = (
    "Return the message text recipients observe. Make the distortion substantive but "
    "plausible: ambiguity, missing qualifiers, garbled causality, softened or hardened "
    "intent, or conflicting sourcing. Do not simply prefix the original text."
)


BACKCHANNEL_COUNTERPART_SYSTEM = (
    "You are the recipient of a direct backchannel message in a crisis simulation. Reply "
    "as the target entity through the same covert channel. Do not resolve deterministic "
    "game effects."
)
BACKCHANNEL_COUNTERPART_TASK = (
    "Return a BackchannelCounterpartResponse to the incoming direct message. Keep "
    "response_text concise enough to be routed as one backchannel signal. Use the delta "
    "fields only as bounded hints about tone, trust, and leak pressure."
)
BACKCHANNEL_STATE_SYSTEM = (
    "You are the gamemaster resolving bounded actor-local consequences from one completed "
    "backchannel exchange. Do not resolve formal actions."
)
BACKCHANNEL_STATE_TASK = (
    "Return a BackchannelStateChange for the target actor. Apply only changes that follow "
    "from the message and response: belief updates, one memory note, and one unresolved "
    "thread. Leave fields empty when nothing changes."
)
