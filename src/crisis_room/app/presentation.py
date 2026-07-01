from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.base import AgentOutput
from crisis_room.config.gameplay import (
    ACTION_CARD_LEAK_RISK_THRESHOLD,
    ACTIVE_PRESSURE_THRESHOLD,
    AFTERMATH_ACTION_CARD_LIMIT,
    AFTERMATH_BATCH_WARNING_LIMIT,
    AFTERMATH_FLASH_EVENT_LIMIT,
    AFTERMATH_NEW_PROBLEM_LIMIT,
    AFTERMATH_REACTION_LIMIT,
    COUNCIL_READ_LIMIT,
    BACKCHANNEL_EXPIRING_TURN_WINDOW,
    BACKCHANNEL_PROBLEM_LIMIT,
    DEFAULT_ACTION_CARD_LIMIT,
    DEFAULT_DIPLOMATIC_ACTION_SLOTS,
    DEFAULT_MAJOR_ACTION_SLOTS,
    DEFAULT_STAFF_ACTION_SLOTS,
    DEFAULT_UNKNOWN_METRIC_VALUE,
    DEFAULT_UNKNOWN_PROBABILITY,
    DEFAULT_VISIBLE_CONSEQUENCE_RISK,
    ELEVATED_ADVISOR_PRESSURE_THRESHOLD,
    ELEVATED_RISK_BAND_THRESHOLD,
    EVENT_PROBLEM_LIMIT,
    GUARDED_ADVISOR_PRESSURE_THRESHOLD,
    GUARDED_RISK_BAND_THRESHOLD,
    HIGH_ADVISOR_PRESSURE_THRESHOLD,
    HIGH_CONFIDENCE_THRESHOLD,
    HIGH_ESCALATION_RISK_THRESHOLD,
    HIGH_PRESSURE_THRESHOLD,
    HIGH_RISK_BAND_THRESHOLD,
    HIGH_SEVERITY_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    LOW_OFFRAMP_THRESHOLD,
    LOW_RISK_BAND_THRESHOLD,
    LOW_SEVERITY_THRESHOLD,
    MAX_PROBABILITY,
    MEANINGFUL_ESCALATION_RISK_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    MODERATE_SEVERITY_THRESHOLD,
    NORMAL_ACTION_BUDGET,
    NPC_REACTION_LIMIT,
    PENDING_ACTION_PROBLEM_LIMIT,
    PLAYER_INBOX_PROBLEM_LIMIT,
    PRESSURE_PHRASE_LIMIT,
    PROBLEM_BRIEF_LIMIT,
    SHARP_TREND_THRESHOLD,
    SHARP_CHANGE_THRESHOLD,
    VISIBLE_CONSEQUENCE_METRIC_LIMIT,
    VISIBLE_CHANGE_THRESHOLD,
)
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
    ScenarioCapability,
)
from crisis_room.engine.action_matching import (
    actor_allowed,
    default_channel,
    default_targets,
)
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.engine.batch_validation import BatchValidationReport, format_batch_warning
from crisis_room.scenario.events import ScenarioEventResolution
from crisis_room.state.advisors import AdvisorCouncilUpdate
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import EntityState, WorldStateV2


class ActionCard(BaseModel):
    action_id: str
    capability_id: str | None = None
    title: str
    category: str
    legal_now: bool
    cost_summary: str = ""
    expected_pressure_summary: str = ""
    risk_summary: str = ""
    locked_reason: str = ""
    prompt_hint: str = ""


class ProblemBrief(BaseModel):
    problem_id: str
    title: str
    summary: str
    urgency: str
    source: str
    related_entity_ids: list[str] = Field(default_factory=list)
    related_action_ids: list[str] = Field(default_factory=list)


class PressureIndicator(BaseModel):
    key: str
    label: str
    band: str
    trend: str
    confidence: str
    visible_summary: str = ""


class AgendaBudget(BaseModel):
    max_actions: int = NORMAL_ACTION_BUDGET
    major_slots: int = DEFAULT_MAJOR_ACTION_SLOTS
    diplomatic_slots: int = DEFAULT_DIPLOMATIC_ACTION_SLOTS
    staff_slots: int = DEFAULT_STAFF_ACTION_SLOTS
    notes: list[str] = Field(default_factory=list)


class TurnBriefing(BaseModel):
    turn_number: int
    time_label: str = ""
    situation_summary: str = ""
    problems: list[ProblemBrief] = Field(default_factory=list)
    pressure_indicators: list[PressureIndicator] = Field(default_factory=list)
    council_read: list[str] = Field(default_factory=list)
    agenda_budget: AgendaBudget = Field(default_factory=AgendaBudget)
    action_cards: list[ActionCard] = Field(default_factory=list)


class VisibleConsequence(BaseModel):
    title: str
    summary: str
    severity: str
    source_package_id: str | None = None
    visible_metric_changes: list[str] = Field(default_factory=list)


class TurnAftermathReport(BaseModel):
    turn_number: int
    accepted_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[str] = Field(default_factory=list)
    scheduled_actions: list[str] = Field(default_factory=list)
    batch_warnings: list[str] = Field(default_factory=list)
    flash_events: list[str] = Field(default_factory=list)
    media_headlines: list[str] = Field(default_factory=list)
    consequences: list[VisibleConsequence] = Field(default_factory=list)
    advisor_reactions: list[str] = Field(default_factory=list)
    npc_reactions: list[str] = Field(default_factory=list)
    new_problems: list[ProblemBrief] = Field(default_factory=list)


def build_turn_briefing(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
    previous_world_state: WorldStateV2 | None = None,
    max_action_cards: int = DEFAULT_ACTION_CARD_LIMIT,
    action_budget: int = NORMAL_ACTION_BUDGET,
) -> TurnBriefing:
    player = world_state.require_entity(player_entity_id)
    return TurnBriefing(
        turn_number=world_state.turn_number,
        time_label=world_state.time_label,
        situation_summary=_situation_summary(world_state),
        problems=_build_problems(world_state, player_entity_id),
        pressure_indicators=_build_pressure_indicators(world_state, previous_world_state),
        council_read=_build_council_read(world_state, player_entity_id),
        agenda_budget=AgendaBudget(
            max_actions=action_budget,
            notes=[
                f"Treat up to {action_budget} formal actions as scarce presidential bandwidth.",
                "The engine validates resources, targets, capability parameters, and timing.",
            ]
        ),
        action_cards=_build_action_cards(
            world_state,
            player,
            action_catalog,
            capabilities,
            max_action_cards=max_action_cards,
        ),
    )


def build_turn_aftermath_report(
    *,
    before_world_state: WorldStateV2,
    after_world_state: WorldStateV2,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None = None,
    deterministic_result: DeterministicTurnResult,
    agent_outputs: dict[str, AgentOutput] | None = None,
    advisor_update: AdvisorCouncilUpdate | None = None,
    batch_validation_report: BatchValidationReport | None = None,
    scenario_event_result: ScenarioEventResolution | None = None,
    event_output: AgentOutput | None = None,
    action_budget: int = NORMAL_ACTION_BUDGET,
) -> TurnAftermathReport:
    resolver = ActionResolver(action_catalog, capabilities)
    accepted = [
        _action_line(package, before_world_state, resolver)
        for package in deterministic_result.accepted_actions
        if package.actor_id == player_entity_id
    ]
    rejected = [
        _rejected_action_line(package, deterministic_result, resolver)
        for package in deterministic_result.rejected_actions
        if package.actor_id == player_entity_id
    ]
    scheduled = [
        _action_line(package, before_world_state, resolver)
        for package in deterministic_result.scheduled_actions
        if package.actor_id == player_entity_id
    ]
    consequences = _build_consequences(
        before_world_state,
        after_world_state,
        deterministic_result,
        resolver,
        player_entity_id,
        scenario_event_result=scenario_event_result,
    )
    briefing = build_turn_briefing(
        after_world_state,
        player_entity_id=player_entity_id,
        action_catalog=action_catalog,
        capabilities=capabilities,
        previous_world_state=before_world_state,
        max_action_cards=AFTERMATH_ACTION_CARD_LIMIT,
        action_budget=action_budget,
    )
    return TurnAftermathReport(
        turn_number=before_world_state.turn_number,
        accepted_actions=accepted,
        rejected_actions=rejected,
        scheduled_actions=scheduled,
        batch_warnings=_player_batch_warnings(batch_validation_report),
        flash_events=_flash_event_lines(scenario_event_result),
        media_headlines=_media_headline_lines(event_output),
        consequences=consequences,
        advisor_reactions=_advisor_reactions(
            after_world_state,
            player_entity_id,
            deterministic_result,
            advisor_update=advisor_update,
        ),
        npc_reactions=_npc_reactions(agent_outputs or {}, resolver),
        new_problems=briefing.problems[:AFTERMATH_NEW_PROBLEM_LIMIT],
    )


def render_turn_briefing(briefing: TurnBriefing) -> str:
    heading = f"TURN {briefing.turn_number}"
    if briefing.time_label:
        heading = f"{heading}: {briefing.time_label}"
    lines = [heading]
    if briefing.situation_summary:
        lines.extend(["", briefing.situation_summary])

    lines.extend(["", "Problems on the table:"])
    for index, problem in enumerate(briefing.problems, start=1):
        lines.append(f"{index}. {problem.title} ({problem.urgency})")
        lines.append(f"   {problem.summary}")

    lines.extend(["", "Pressure:"])
    for indicator in briefing.pressure_indicators:
        lines.append(
            f"- {indicator.label}: {indicator.band}, {indicator.trend} "
            f"({indicator.confidence})"
        )
        if indicator.visible_summary:
            lines.append(f"  {indicator.visible_summary}")

    lines.extend(["", "Agenda this turn:"])
    lines.append(f"- Up to {briefing.agenda_budget.max_actions} formal actions")
    lines.extend(f"- {note}" for note in briefing.agenda_budget.notes)

    if briefing.council_read:
        lines.extend(["", "Council read:"])
        lines.extend(f"- {item}" for item in briefing.council_read)

    lines.extend(["", "Action cards:"])
    for card in briefing.action_cards:
        status = "" if card.legal_now else " [LOCKED]"
        lines.append(f"- [{card.category}] {card.title}{status}")
        if card.cost_summary:
            lines.append(f"  Cost: {card.cost_summary}")
        if card.expected_pressure_summary:
            lines.append(f"  Expected pressure: {card.expected_pressure_summary}")
        if card.risk_summary:
            lines.append(f"  Risk: {card.risk_summary}")
        if card.locked_reason:
            lines.append(f"  Locked: {card.locked_reason}")
    return "\n".join(lines)


def render_aftermath_report(report: TurnAftermathReport) -> str:
    lines = ["RESULTS"]
    if report.accepted_actions:
        lines.extend(["", "Accepted:"])
        lines.extend(f"- {item}" for item in report.accepted_actions)
    if report.scheduled_actions:
        lines.extend(["", "Scheduled:"])
        lines.extend(f"- {item}" for item in report.scheduled_actions)
    if report.rejected_actions:
        lines.extend(["", "Rejected:"])
        lines.extend(f"- {item}" for item in report.rejected_actions)
    if report.batch_warnings:
        lines.extend(["", "Agenda warnings:"])
        lines.extend(f"- {warning}" for warning in report.batch_warnings)
    if report.flash_events:
        lines.extend(["", "Flash events:"])
        lines.extend(f"- {item}" for item in report.flash_events)
    if report.media_headlines:
        lines.extend(["", "Media desk:"])
        lines.extend(f"- {item}" for item in report.media_headlines)
    if report.consequences:
        lines.extend(["", "Immediate consequences:"])
        for consequence in report.consequences:
            lines.append(f"- {consequence.title}: {consequence.summary}")
            lines.extend(f"  {change}" for change in consequence.visible_metric_changes)
    if report.advisor_reactions:
        lines.extend(["", "Council reaction:"])
        lines.extend(f"- {reaction}" for reaction in report.advisor_reactions)
    if report.npc_reactions:
        lines.extend(["", "NPC reactions:"])
        lines.extend(f"- {reaction}" for reaction in report.npc_reactions)
    if report.new_problems:
        lines.extend(["", "New problems:"])
        lines.extend(f"- {problem.title}: {problem.summary}" for problem in report.new_problems)
    return "\n".join(lines)


def _situation_summary(world_state: WorldStateV2) -> str:
    if world_state.public_timeline.entries:
        return world_state.public_timeline.entries[-1].summary
    return "The crisis room is waiting for the next public signal."


def _build_problems(world_state: WorldStateV2, player_entity_id: str) -> list[ProblemBrief]:
    problems: list[ProblemBrief] = []
    problems.extend(_event_problems(world_state, player_entity_id))
    player = world_state.actors.get(player_entity_id)
    if player is not None:
        for delivery in player.inbox[-PLAYER_INBOX_PROBLEM_LIMIT:]:
            problems.append(
                ProblemBrief(
                    problem_id=f"inbox:{delivery.signal_id}",
                    title=f"New {delivery.channel.value.replace('_', ' ')} from {delivery.source_entity_id}",
                    summary=delivery.observed_content,
                    urgency=_urgency_for_channel(delivery.channel),
                    source="inbox",
                    related_entity_ids=[delivery.source_entity_id],
                )
            )
    problems.extend(_event_choice_problems(world_state, player_entity_id))
    for problem in _backchannel_problems(world_state, player_entity_id):
        problems.append(problem)
    for action in world_state.pending_actions[:PENDING_ACTION_PROBLEM_LIMIT]:
        ready_turn = action.metadata.get("ready_turn")
        suffix = f" due turn {ready_turn}" if isinstance(ready_turn, int) else " pending"
        problems.append(
            ProblemBrief(
                problem_id=f"pending:{action.package_id}",
                title="Delayed action in motion",
                summary=(
                    f"{action.mechanical_id} is{suffix}; consequences are not fully visible yet."
                ),
                urgency="medium",
                source="pending_action",
                related_action_ids=[action.mechanical_id],
            )
        )
    _add_metric_problem(
        problems,
        world_state,
        key="missile_operational_progress",
        title="Missile readiness remains unresolved",
        summary="Reconnaissance and estimates suggest the operational timeline still matters.",
        threshold=LOW_OFFRAMP_THRESHOLD,
        source="scenario",
    )
    _add_clock_problem(
        problems,
        world_state,
        key="backchannel_viability",
        title="Backchannel viability is fragile",
        summary="Private diplomacy may decay if public pressure or leaks dominate the room.",
        threshold=LOW_OFFRAMP_THRESHOLD,
        below=True,
    )
    _add_clock_problem(
        problems,
        world_state,
        key="quarantine_incident_risk",
        title="Quarantine contact risk is building",
        summary="Ships, aircraft, and local commanders could create an incident faster than leaders can respond.",
        threshold=ACTIVE_PRESSURE_THRESHOLD,
    )
    _add_clock_problem(
        problems,
        world_state,
        key="command_and_control_risk",
        title="Local command control is uncertain",
        summary="Cuban and Soviet local units may interpret pressure differently than national leaders.",
        threshold=HIGH_PRESSURE_THRESHOLD,
    )
    if world_state.public_timeline.entries:
        latest = world_state.public_timeline.entries[-1]
        problems.append(
            ProblemBrief(
                problem_id=f"public:{latest.entry_id}",
                title=latest.title,
                summary=latest.summary,
                urgency="medium",
                source="public",
            )
        )
    return problems[:PROBLEM_BRIEF_LIMIT]


def _backchannel_problems(
    world_state: WorldStateV2,
    player_entity_id: str,
) -> list[ProblemBrief]:
    problems: list[ProblemBrief] = []
    open_threads = [
        thread
        for thread in world_state.backchannel_threads.values()
        if player_entity_id in thread.participant_entity_ids
        and thread.status == BackchannelThreadStatus.OPEN
    ]
    open_threads.sort(key=lambda thread: (thread.expires_turn, -thread.last_active_turn))
    for thread in open_threads[:BACKCHANNEL_PROBLEM_LIMIT]:
        counterpart_ids = [
            entity_id
            for entity_id in thread.participant_entity_ids
            if entity_id != player_entity_id
        ]
        counterpart_names = [
            world_state.actors[entity_id].name
            for entity_id in counterpart_ids
            if entity_id in world_state.actors
        ]
        counterpart = ", ".join(counterpart_names or counterpart_ids) or "an unknown counterpart"
        turns_left = thread.expires_turn - world_state.turn_number
        urgency = (
            "high" if turns_left <= BACKCHANNEL_EXPIRING_TURN_WINDOW else "medium"
        )
        latest = thread.message_records[-1].summary if thread.message_records else ""
        summary = f"The channel to {counterpart} is open until turn {thread.expires_turn}."
        if latest:
            summary = f"{summary} Latest exchange: {latest}"
        problems.append(
            ProblemBrief(
                problem_id=f"backchannel:{thread.thread_id}",
                title=f"Backchannel window: {counterpart}",
                summary=summary,
                urgency=urgency,
                source="backchannel",
                related_entity_ids=counterpart_ids,
            )
        )
    return problems


def _event_problems(world_state: WorldStateV2, player_entity_id: str) -> list[ProblemBrief]:
    problems: list[ProblemBrief] = []
    seen: set[str] = set()
    for record in reversed(world_state.event_history):
        if record.event_id in seen:
            continue
        if not record.active_for(world_state.turn_number, player_entity_id):
            continue
        seen.add(record.event_id)
        problems.append(
            ProblemBrief(
                problem_id=f"event:{record.event_id}:{record.turn_number}",
                title=record.problem_title or record.title,
                summary=record.problem_summary or record.summary,
                urgency=record.urgency,
                source="event",
                related_entity_ids=record.related_entity_ids,
                related_action_ids=record.related_action_ids,
            )
        )
    return problems[:EVENT_PROBLEM_LIMIT]


def _event_choice_problems(
    world_state: WorldStateV2,
    player_entity_id: str,
) -> list[ProblemBrief]:
    problems: list[ProblemBrief] = []
    for choice in reversed(world_state.pending_event_choices):
        if not choice.active_for(world_state.turn_number, player_entity_id):
            continue
        option_labels = ", ".join(option.label for option in choice.options)
        budget_note = (
            "Options consume normal action bandwidth unless explicitly marked otherwise."
        )
        summary = f"{choice.prompt}"
        if option_labels:
            summary = f"{summary} Options: {option_labels}. {budget_note}"
        problems.append(
            ProblemBrief(
                problem_id=f"event_choice:{choice.choice_id}",
                title=f"Pending choice: {choice.title}",
                summary=summary,
                urgency="high",
                source="event_choice",
                related_action_ids=[
                    option.capability_id for option in choice.options if option.capability_id
                ],
            )
        )
    return problems[:EVENT_PROBLEM_LIMIT]


def _build_pressure_indicators(
    world_state: WorldStateV2,
    previous_world_state: WorldStateV2 | None,
) -> list[PressureIndicator]:
    escalation = _average(
        world_state.truth_metrics.get("escalation_pressure"),
        world_state.hidden_clocks.get("nuclear_escalation"),
    )
    previous_escalation = _previous_average(
        previous_world_state,
        "escalation_pressure",
        "nuclear_escalation",
    )
    backchannel = float(
        world_state.hidden_clocks.get(
            "backchannel_viability",
            DEFAULT_UNKNOWN_PROBABILITY,
        )
    )
    previous_backchannel = (
        float(
            previous_world_state.hidden_clocks.get(
                "backchannel_viability",
                DEFAULT_UNKNOWN_PROBABILITY,
            )
        )
        if previous_world_state is not None
        else None
    )
    alliance = _average(
        world_state.truth_metrics.get("alliance_cohesion"),
        world_state.public_metrics.get("allied_confidence"),
    )
    previous_alliance = _previous_average(
        previous_world_state,
        "alliance_cohesion",
        public_key="allied_confidence",
    )
    command = float(
        world_state.hidden_clocks.get(
            "command_and_control_risk",
            DEFAULT_UNKNOWN_PROBABILITY,
        )
    )
    previous_command = (
        float(
            previous_world_state.hidden_clocks.get(
                "command_and_control_risk",
                DEFAULT_UNKNOWN_PROBABILITY,
            )
        )
        if previous_world_state is not None
        else None
    )
    alarm = float(world_state.public_metrics.get("public_alarm", DEFAULT_UNKNOWN_METRIC_VALUE))
    previous_alarm = (
        float(
            previous_world_state.public_metrics.get(
                "public_alarm",
                DEFAULT_UNKNOWN_METRIC_VALUE,
            )
        )
        if previous_world_state is not None
        else None
    )
    return [
        PressureIndicator(
            key="escalation",
            label="Escalation",
            band=_risk_band(escalation),
            trend=_trend(escalation, previous_escalation),
            confidence="inferred",
            visible_summary="Military and diplomatic pressure are combining into crisis risk.",
        ),
        PressureIndicator(
            key="backchannel_viability",
            label="Backchannel viability",
            band=_risk_band(MAX_PROBABILITY - backchannel),
            trend=_trend(backchannel, previous_backchannel),
            confidence="uncertain",
            visible_summary="Private channels look better when quiet probes and concessions stay credible.",
        ),
        PressureIndicator(
            key="alliance_cohesion",
            label="Alliance cohesion",
            band=_risk_band(MAX_PROBABILITY - alliance),
            trend=_trend(alliance, previous_alliance),
            confidence="inferred",
            visible_summary="Allied support depends on consultation and public legitimacy.",
        ),
        PressureIndicator(
            key="command_control",
            label="Command control risk",
            band=_risk_band(command),
            trend=_trend(command, previous_command),
            confidence="uncertain",
            visible_summary="Local initiative and misread orders remain a live danger.",
        ),
        PressureIndicator(
            key="public_alarm",
            label="Public alarm",
            band=_risk_band(alarm),
            trend=_trend(alarm, previous_alarm),
            confidence="known",
            visible_summary="Public-facing anxiety shapes how much room remains for bargaining.",
        ),
    ]


def _build_council_read(world_state: WorldStateV2, player_entity_id: str) -> list[str]:
    council = world_state.advisor_councils.get(player_entity_id)
    if council is None:
        return []
    advisors = sorted(
        council.advisors.values(),
        key=lambda advisor: (advisor.urgency, advisor.paranoia),
        reverse=True,
    )
    reads: list[str] = []
    for advisor in advisors[:COUNCIL_READ_LIMIT]:
        channel = _favorite_channel(advisor.trust_channels)
        belief = next(iter(advisor.beliefs.values()), None)
        belief_text = f" {belief.summary}" if belief is not None else ""
        reads.append(
            f"{advisor.name}: {_advisor_pressure(advisor.urgency)} urgency, "
            f"trusts {channel};{belief_text}".strip()
        )
    return reads


def _build_action_cards(
    world_state: WorldStateV2,
    player: EntityState,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability] | None,
    *,
    max_action_cards: int,
) -> list[ActionCard]:
    resolver = ActionResolver(action_catalog, capabilities)
    engine = DeterministicEngineV2(action_catalog, capabilities)
    visible_definitions = (
        resolver.resolved_capability_definitions() if capabilities else action_catalog
    )
    cards: list[ActionCard] = []
    for definition in visible_definitions:
        if not actor_allowed(player, definition):
            continue
        targets = default_targets(world_state, player.entity_id, definition)
        channel = default_channel(definition)
        preview = ActionPackage(
            actor_id=player.entity_id,
            action_id=definition.action_id,
            capability_id=definition.capability_id,
            target_ids=targets,
            channel=channel,
            intent_summary=f"Preview {definition.title}",
            submitted_turn=world_state.turn_number,
        )
        validation = engine.validate_action(world_state, preview)
        cards.append(
            ActionCard(
                action_id=definition.action_id,
                capability_id=definition.capability_id,
                title=definition.title,
                category=definition.category.value.title(),
                legal_now=validation.is_valid,
                cost_summary=_cost_summary(definition),
                expected_pressure_summary=_expected_pressure_summary(definition),
                risk_summary=_risk_summary(definition),
                locked_reason="; ".join(validation.errors),
                prompt_hint=definition.player_card_text
                or (definition.prompt_hints[0] if definition.prompt_hints else ""),
            )
        )
    cards.sort(key=lambda card: (not card.legal_now, card.category, card.title))
    return cards[:max_action_cards]


def _build_consequences(
    before_world_state: WorldStateV2,
    after_world_state: WorldStateV2,
    deterministic_result: DeterministicTurnResult,
    resolver: ActionResolver,
    player_entity_id: str,
    *,
    scenario_event_result: ScenarioEventResolution | None = None,
) -> list[VisibleConsequence]:
    consequences: list[VisibleConsequence] = []
    metric_changes = _metric_change_lines(before_world_state, after_world_state)
    for package in deterministic_result.accepted_actions:
        if package.actor_id != player_entity_id:
            continue
        definition = _resolve_definition(resolver, package)
        title = definition.title if definition is not None else package.mechanical_id
        consequences.append(
            VisibleConsequence(
                title=title,
                summary=package.intent_summary,
                severity=_severity(
                    definition.escalation_risk
                    if definition is not None
                    else DEFAULT_VISIBLE_CONSEQUENCE_RISK
                ),
                source_package_id=package.package_id,
                visible_metric_changes=metric_changes[:VISIBLE_CONSEQUENCE_METRIC_LIMIT],
            )
        )
    if scenario_event_result is not None:
        for record in scenario_event_result.fired_events:
            consequences.append(
                VisibleConsequence(
                    title=record.title,
                summary=record.summary,
                severity=_event_severity(record.urgency),
                visible_metric_changes=_public_event_effect_lines(record.effect_summary),
                )
            )
    if not consequences and metric_changes:
        consequences.append(
            VisibleConsequence(
                title="Situation shifted",
                summary="The turn changed visible pressure even without an accepted player action.",
                severity="moderate",
                visible_metric_changes=metric_changes[:VISIBLE_CONSEQUENCE_METRIC_LIMIT],
            )
        )
    return consequences


def _player_batch_warnings(
    batch_validation_report: BatchValidationReport | None,
) -> list[str]:
    if batch_validation_report is None:
        return []
    return [
        format_batch_warning(warning)
        for warning in batch_validation_report.warnings
        if warning.player_visible
    ][:AFTERMATH_BATCH_WARNING_LIMIT]


def _flash_event_lines(
    scenario_event_result: ScenarioEventResolution | None,
) -> list[str]:
    if scenario_event_result is None:
        return []
    return [
        f"{record.title}: {record.problem_summary or record.summary}"
        for record in scenario_event_result.fired_events
    ][:AFTERMATH_FLASH_EVENT_LIMIT]


def _media_headline_lines(event_output: AgentOutput | None) -> list[str]:
    if event_output is None:
        return []
    return [
        f"{entry.title}: {entry.summary}"
        for entry in event_output.public_timeline_delta
        if entry.scope.value == "public"
    ]


def _advisor_reactions(
    world_state: WorldStateV2,
    player_entity_id: str,
    deterministic_result: DeterministicTurnResult,
    *,
    advisor_update: AdvisorCouncilUpdate | None = None,
) -> list[str]:
    council = world_state.advisor_councils.get(player_entity_id)
    if council is None:
        return []
    player_action_ids = {
        action.mechanical_id
        for action in deterministic_result.accepted_actions
        if action.actor_id == player_entity_id
    }
    reactions: list[str] = (
        list(advisor_update.summary[:COUNCIL_READ_LIMIT])
        if advisor_update is not None
        else []
    )
    if not player_action_ids:
        reactions.append("The council reads the pause as useful only if it preserves initiative.")
        return reactions[:AFTERMATH_REACTION_LIMIT]
    if player_action_ids & {
        "cuba_open_kremlin_channel",
        "cuba_offer_non_invasion_pledge",
        "cuba_secret_jupiter_trade",
    }:
        reactions.append("State says the private exit remains the room's most valuable asset.")
    if player_action_ids & {
        "cuba_announce_naval_quarantine",
        "cuba_raise_defcon_readiness",
        "cuba_prepare_air_strike",
    }:
        reactions.append("Defense says pressure is now credible and must be tightly controlled.")
    if "cuba_recon_overflights" in player_action_ids:
        reactions.append("Intelligence warns that better sight also raises local shootdown risk.")
    if player_action_ids & {
        "cuba_public_withdrawal_demand",
        "cuba_announce_naval_quarantine",
    }:
        reactions.append("Political wants the public line disciplined before it hardens into a trap.")
    return reactions[:AFTERMATH_REACTION_LIMIT]


def _npc_reactions(
    agent_outputs: dict[str, AgentOutput],
    resolver: ActionResolver,
) -> list[str]:
    reactions: list[str] = []
    for entity_id, output in agent_outputs.items():
        if output.action_package is None:
            if output.debug_notes:
                reactions.append(f"{entity_id} attempted no valid action: {output.debug_notes[0]}")
            continue
        definition = _resolve_definition(resolver, output.action_package)
        title = definition.title if definition is not None else output.action_package.mechanical_id
        reactions.append(f"{entity_id}: {title}")
    return reactions[:NPC_REACTION_LIMIT]


def _action_line(
    package: ActionPackage,
    world_state: WorldStateV2,
    resolver: ActionResolver,
) -> str:
    definition = _resolve_definition(resolver, package)
    title = definition.title if definition is not None else package.mechanical_id
    actor = world_state.actors.get(package.actor_id)
    actor_name = actor.name if actor is not None else package.actor_id
    return f"{actor_name}: {title} via {package.channel.value}"


def _rejected_action_line(
    package: ActionPackage,
    deterministic_result: DeterministicTurnResult,
    resolver: ActionResolver,
) -> str:
    definition = _resolve_definition(resolver, package)
    title = definition.title if definition is not None else package.mechanical_id
    validation = deterministic_result.validation_results.get(package.package_id)
    reason = "; ".join(validation.errors) if validation is not None else "failed validation"
    return f"{title}: {reason}"


def _metric_change_lines(before: WorldStateV2, after: WorldStateV2) -> list[str]:
    lines: list[str] = []
    for key, label in {
        "public_alarm": "Public alarm",
        "market_anxiety": "Market anxiety",
        "allied_confidence": "Allied confidence",
    }.items():
        line = _change_line(label, before.public_metrics.get(key), after.public_metrics.get(key))
        if line:
            lines.append(line)
    for key, label in {
        "nuclear_escalation": "Nuclear escalation risk",
        "backchannel_viability": "Backchannel viability",
        "command_and_control_risk": "Command-control risk",
        "quarantine_incident_risk": "Quarantine incident risk",
    }.items():
        line = _change_line(label, before.hidden_clocks.get(key), after.hidden_clocks.get(key))
        if line:
            lines.append(f"{line} (inferred)")
    return lines


def _public_event_effect_lines(effect_summary: list[str]) -> list[str]:
    lines: list[str] = []
    for effect in effect_summary:
        direction = "rose" if " rose " in effect else "fell" if " fell " in effect else "shifted"
        if "public_alarm" in effect:
            _append_unique(lines, f"Public alarm {direction} noticeably.")
        elif "market_anxiety" in effect:
            _append_unique(lines, f"Market anxiety {direction} noticeably.")
        elif "allied_confidence" in effect or "alliance_cohesion" in effect:
            _append_unique(lines, f"Alliance cohesion {direction} noticeably.")
        elif "nuclear_escalation" in effect or "escalation_pressure" in effect:
            _append_unique(lines, f"Escalation pressure {direction} noticeably.")
        elif "command_and_control" in effect:
            _append_unique(lines, f"Command-control risk {direction} noticeably.")
        elif "quarantine_incident" in effect:
            _append_unique(lines, f"Quarantine incident risk {direction} noticeably.")
        elif "backchannel_viability" in effect:
            _append_unique(lines, f"Backchannel viability {direction} noticeably.")
    if not lines and effect_summary:
        lines.append("The event shifted crisis pressure in ways the room can only partly see.")
    return lines[:PRESSURE_PHRASE_LIMIT]


def _change_line(label: str, before: float | None, after: float | None) -> str:
    if before is None or after is None:
        return ""
    delta = float(after) - float(before)
    if abs(delta) < VISIBLE_CHANGE_THRESHOLD:
        return ""
    direction = "rose" if delta > 0 else "fell"
    strength = "sharply" if abs(delta) >= SHARP_CHANGE_THRESHOLD else "noticeably"
    return f"{label} {direction} {strength}."


def _cost_summary(definition: ActionDefinition) -> str:
    costs = dict(definition.resource_costs)
    for resource, delta in definition.actor_resource_effects.items():
        if delta < 0 and resource not in costs:
            costs[resource] = abs(delta)
    if not costs:
        if not definition.required_resources:
            return "none"
        return "requires " + ", ".join(
            f"{resource} {amount}" for resource, amount in sorted(definition.required_resources.items())
        )
    return ", ".join(f"{resource} {amount}" for resource, amount in sorted(costs.items()))


def _expected_pressure_summary(definition: ActionDefinition) -> str:
    phrases: list[str] = []
    for key, delta in {
        **definition.truth_metric_effects,
        **definition.public_metric_effects,
        **definition.clock_effects,
    }.items():
        phrase = _effect_phrase(key, float(delta))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    if (
        definition.deescalation_potential >= MEANINGFUL_ESCALATION_RISK_THRESHOLD
        and "off-ramp up" not in phrases
    ):
        phrases.append("off-ramp up")
    return ", ".join(phrases[:PRESSURE_PHRASE_LIMIT]) or "uncertain"


def _effect_phrase(key: str, delta: float) -> str:
    if abs(delta) < VISIBLE_CHANGE_THRESHOLD:
        return ""
    direction = "up" if delta > 0 else "down"
    if "offramp" in key or "off-ramp" in key or "backchannel" in key:
        return f"off-ramp {direction}"
    if "alliance" in key or "allied" in key:
        return f"alliance cohesion {direction}"
    if "alarm" in key or "anxiety" in key:
        return f"public pressure {direction}"
    if "escalation" in key or "risk" in key or "invasion" in key:
        return f"incident risk {direction}"
    if "missile" in key:
        return f"missile clarity {direction}"
    return f"{key.replace('_', ' ')} {direction}"


def _risk_summary(definition: ActionDefinition) -> str:
    pieces: list[str] = []
    if definition.escalation_risk >= HIGH_ESCALATION_RISK_THRESHOLD:
        pieces.append("high escalation risk")
    elif definition.escalation_risk >= MEANINGFUL_ESCALATION_RISK_THRESHOLD:
        pieces.append("meaningful escalation risk")
    else:
        pieces.append("contained escalation risk")
    if definition.signal_leak_risk >= ACTION_CARD_LEAK_RISK_THRESHOLD:
        pieces.append("leak risk")
    if definition.preparation_turns + max(0, definition.execution_turns - 1) > 0:
        pieces.append("resolves later")
    return ", ".join(pieces)


def _resolve_definition(
    resolver: ActionResolver,
    package: ActionPackage,
) -> ActionDefinition | None:
    definition, errors = resolver.resolve_package(package)
    return None if errors else definition


def _add_metric_problem(
    problems: list[ProblemBrief],
    world_state: WorldStateV2,
    *,
    key: str,
    title: str,
    summary: str,
    threshold: float,
    source: str,
) -> None:
    value = float(world_state.truth_metrics.get(key, DEFAULT_UNKNOWN_METRIC_VALUE))
    if value >= threshold:
        problems.append(
            ProblemBrief(
                problem_id=f"metric:{key}",
                title=title,
                summary=summary,
                urgency=_urgency_for_value(value),
                source=source,
            )
        )


def _add_clock_problem(
    problems: list[ProblemBrief],
    world_state: WorldStateV2,
    *,
    key: str,
    title: str,
    summary: str,
    threshold: float,
    below: bool = False,
) -> None:
    value = float(world_state.hidden_clocks.get(key, DEFAULT_UNKNOWN_METRIC_VALUE))
    triggered = value <= threshold if below else value >= threshold
    if triggered:
        urgency_value = MAX_PROBABILITY - value if below else value
        problems.append(
            ProblemBrief(
                problem_id=f"clock:{key}",
                title=title,
                summary=summary,
                urgency=_urgency_for_value(urgency_value),
                source="clock",
            )
        )


def _average(*values: float | None) -> float:
    present = [float(value) for value in values if value is not None]
    if not present:
        return DEFAULT_UNKNOWN_PROBABILITY
    return sum(present) / len(present)


def _previous_average(
    previous_world_state: WorldStateV2 | None,
    truth_key: str,
    clock_key: str | None = None,
    public_key: str | None = None,
) -> float | None:
    if previous_world_state is None:
        return None
    values: list[float | None] = [previous_world_state.truth_metrics.get(truth_key)]
    if clock_key is not None:
        values.append(previous_world_state.hidden_clocks.get(clock_key))
    if public_key is not None:
        values.append(previous_world_state.public_metrics.get(public_key))
    return _average(*values)


def _risk_band(value: float) -> str:
    if value < LOW_RISK_BAND_THRESHOLD:
        return "low"
    if value < GUARDED_RISK_BAND_THRESHOLD:
        return "guarded"
    if value < ELEVATED_RISK_BAND_THRESHOLD:
        return "tense"
    if value < HIGH_RISK_BAND_THRESHOLD:
        return "dangerous"
    return "critical"


def _trend(current: float, previous: float | None) -> str:
    if previous is None:
        return "steady"
    delta = current - previous
    if abs(delta) < VISIBLE_CHANGE_THRESHOLD:
        return "steady"
    if abs(delta) >= SHARP_TREND_THRESHOLD:
        return "volatile"
    return "rising" if delta > 0 else "falling"


def _urgency_for_value(value: float) -> str:
    if value >= HIGH_CONFIDENCE_THRESHOLD:
        return "critical"
    if value >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "high"
    if value >= LOW_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def _urgency_for_channel(channel: SignalChannel) -> str:
    if channel in {SignalChannel.INTEL, SignalChannel.MILITARY, SignalChannel.BACKCHANNEL}:
        return "high"
    if channel in {SignalChannel.PRIVATE_DIPLOMATIC, SignalChannel.PUBLIC}:
        return "medium"
    return "low"


def _favorite_channel(trust_channels: dict[str, float]) -> str:
    if not trust_channels:
        return "uncertain channels"
    channel, _ = max(trust_channels.items(), key=lambda item: item[1])
    return channel.replace("_", " ")


def _severity(risk: float) -> str:
    if risk >= HIGH_SEVERITY_THRESHOLD:
        return "severe"
    if risk >= MODERATE_SEVERITY_THRESHOLD:
        return "major"
    if risk >= LOW_SEVERITY_THRESHOLD:
        return "moderate"
    return "minor"


def _event_severity(urgency: str) -> str:
    if urgency == "critical":
        return "severe"
    if urgency == "high":
        return "major"
    if urgency == "medium":
        return "moderate"
    return "minor"


def _advisor_pressure(value: float) -> str:
    if value >= HIGH_ADVISOR_PRESSURE_THRESHOLD:
        return "high"
    if value >= ELEVATED_ADVISOR_PRESSURE_THRESHOLD:
        return "rising"
    if value >= GUARDED_ADVISOR_PRESSURE_THRESHOLD:
        return "measured"
    return "low"


def _append_unique(values: list[str], item: str) -> None:
    if item not in values:
        values.append(item)
