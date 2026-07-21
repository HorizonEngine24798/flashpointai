"""Build room-oriented GUI views from a live game session."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from crisis_room.app.gui_assets import (
    ADVISOR_ASSET_KEYS,
    ROOM_ASSET_KEYS,
    UI_ASSET_KEYS,
    advisor_asset_key,
    lighting_band,
    scenario_thumbnail_key,
)
from crisis_room.app.gui_schema import (
    ActionCardView,
    ActionSourceGroupView,
    AdvisorCouncilView,
    AdvisorDialogueView,
    AdvisorFigureView,
    AdvisorLineView,
    AdvisorProposalView,
    AdvisorRoomView,
    AgendaConflictView,
    AgendaItemView,
    AgendaView,
    AssetManifestView,
    BackchannelThreadView,
    BreakingNewsItemView,
    ChannelMessageView,
    ChannelThreadView,
    ControlRoomView,
    DebugView,
    EndingOfferView,
    GameView,
    MediaRoomView,
    NavigationBadgeView,
    PendingEventChoiceView,
    PendingEventOptionView,
    PlanPreviewActionView,
    PlanPreviewView,
    PressureView,
    ProblemView,
    ResourceView,
    SaveSummaryView,
    ScenarioOptionView,
    ScenarioView,
    SceneView,
    SettingsFieldView,
    SettingsView,
    StartMenuView,
    TimelineEntryView,
    TurnResultView,
    TurnView,
    action_card_id,
    event_choice_card_id,
)
from crisis_room.app.presentation import ActionCard, TurnAftermathReport, TurnBriefing
from crisis_room.engine.actions import ActionPackage, ActionResolver
from crisis_room.scenario.endings import active_ending_offers
from crisis_room.state.backchannels import BackchannelThreadStatus
from crisis_room.state.events import ScenarioEventChoiceRecord
from crisis_room.state.timelines import TimelineEntry
from crisis_room.state.world import WorldStateV2

if TYPE_CHECKING:
    from crisis_room.app.session import GameSession


def build_game_view(session: GameSession) -> GameView:
    world = session.world
    briefing = session.build_briefing()
    resources = _resource_views(world, session.player_id)
    problems = _problem_views(briefing)
    pressure = _pressure_views(briefing)
    council = _advisor_council_view(session)
    action_groups = _action_groups(session, briefing)
    agenda = _agenda_view(session)
    saves = session.list_saves()
    timeline = _timeline_views(world, session.player_id)
    latest_result = _turn_result_view(session)
    advisor_dialogue = _advisor_dialogue_view(session)
    backchannels = _backchannel_views(world, session.player_id)
    pending_event_choices = _pending_event_choice_views(world, session.player_id)
    ending_offers = _ending_offer_views(world, session.player_id)
    ticker = _ticker_items(world, timeline, pending_event_choices)
    conflicts = _agenda_conflicts(session, agenda)
    scenario_view = ScenarioView(
        scenario_id=session.scenario.scenario_id,
        title=session.scenario.metadata.title,
        historical_period=session.scenario.metadata.historical_period,
        description=session.scenario.metadata.description,
        player_entity_id=session.player_id,
    )
    turn_view = TurnView(
        turn_number=world.turn_number,
        time_label=world.time_label,
        situation_summary=briefing.situation_summary,
        accepted_ending_id=world.accepted_ending_id,
        final_summary=world.final_summary,
        is_concluded=bool(world.accepted_ending_id),
    )
    scene = _scene_view(
        session,
        action_groups=action_groups,
        backchannels=backchannels,
    )
    return GameView(
        scenario=scenario_view,
        turn=turn_view,
        scene=scene,
        start_menu=_start_menu_view(saves),
        scenario_options=[_scenario_option_view(session.scenario)],
        ticker=ticker,
        nav_badges=_nav_badges(scene, action_groups, backchannels),
        control_room=ControlRoomView(
            situation_summary=briefing.situation_summary,
            open_problems=problems,
            recent_results=_recent_result_lines(latest_result),
            latest_result=latest_result,
            critical_warnings=list(briefing.critical_warnings),
            pressure=pressure,
            resources=resources,
            agenda=agenda,
            agenda_conflicts=conflicts,
        ),
        advisor_room=_advisor_room_view(
            council=council,
            council_read=briefing.council_read,
            action_groups=action_groups,
            agenda=agenda,
            conflicts=conflicts,
            latest_dialogue=advisor_dialogue,
        ),
        media_room=MediaRoomView(
            news_items=ticker,
            timeline=timeline,
            channel_threads=_channel_thread_views(backchannels, session),
            has_unread=scene.has_new_backchannels,
        ),
        settings=_settings_view(),
        asset_manifest=_asset_manifest_view(),
        agenda=agenda,
        plan_preview=_plan_preview_view(session),
        pending_event_choices=pending_event_choices,
        ending_offers=ending_offers,
        saves=saves,
        debug=_debug_view(session) if session.debug_visible else None,
    )


def build_turn_result_view(
    report: TurnAftermathReport,
    *,
    rendered_text: str = "",
) -> TurnResultView:
    return TurnResultView(
        turn_number=report.turn_number,
        accepted_actions=list(report.accepted_actions),
        resolved_actions=list(report.resolved_actions),
        rejected_actions=list(report.rejected_actions),
        resource_blocked_actions=list(report.resource_blocked_actions),
        scheduled_actions=list(report.scheduled_actions),
        critical_warnings=list(report.critical_warnings),
        batch_warnings=list(report.batch_warnings),
        flash_events=list(report.flash_events),
        media_headlines=list(report.media_headlines),
        pressure_updates=list(report.pressure_updates),
        consequences=_consequence_lines(report),
        advisor_reactions=list(report.advisor_reactions),
        npc_reactions=list(report.npc_reactions),
        new_problems=[
            ProblemView(
                problem_id=problem.problem_id,
                title=problem.title,
                summary=problem.summary,
                urgency=problem.urgency,
                source=problem.source,
            )
            for problem in report.new_problems
        ],
        rendered_text=rendered_text,
    )


def _scene_view(
    session: GameSession,
    *,
    action_groups: list[ActionSourceGroupView],
    backchannels: list[BackchannelThreadView],
) -> SceneView:
    tension_level = _tension_level(session.world)
    return SceneView(
        tension_level=tension_level,
        room_asset_key=f"rooms/control_tension_{tension_level}",
        lighting_band=lighting_band(tension_level),
        has_new_results=bool(session.latest_aftermath_report or session.latest_result_rendered),
        has_new_backchannels=bool(
            backchannels
            and (
                session.world.backchannel_update_history
                or any(thread.latest for thread in backchannels)
            )
        ),
        has_pending_proposals=any(
            group.source_type == "council" and any(card.legal_now for card in group.cards)
            for group in action_groups
        ),
    )


def _start_menu_view(saves: list[SaveSummaryView]) -> StartMenuView:
    recent_save = next((save for save in saves if save.compatible), None)
    return StartMenuView(
        continue_available=recent_save is not None,
        recent_save=recent_save,
    )


def _scenario_option_view(scenario: Any) -> ScenarioOptionView:
    return ScenarioOptionView(
        scenario_id=scenario.scenario_id,
        title=scenario.metadata.title,
        historical_period=scenario.metadata.historical_period,
        description=scenario.metadata.description,
        thumbnail_asset_key=scenario_thumbnail_key(scenario.scenario_id),
    )


def _ticker_items(
    world: WorldStateV2,
    timeline: list[TimelineEntryView],
    pending_event_choices: list[PendingEventChoiceView],
) -> list[BreakingNewsItemView]:
    items: list[BreakingNewsItemView] = []
    for choice in pending_event_choices:
        items.append(
            BreakingNewsItemView(
                item_id=f"choice:{choice.choice_id}",
                title=choice.title,
                summary=choice.prompt,
                source="situation",
                urgency="critical",
                turn=world.turn_number,
                is_new=True,
            )
        )
    for entry in timeline:
        if entry.scope != "public":
            continue
        items.append(
            BreakingNewsItemView(
                item_id=entry.entry_id,
                title=entry.title,
                summary=entry.summary,
                source=entry.source or "public",
                urgency=_timeline_urgency(entry),
                turn=entry.turn,
                is_new=entry.turn >= world.turn_number - 1,
            )
        )
    if not items:
        items.append(
            BreakingNewsItemView(
                item_id="ticker:quiet",
                title="No Public Bulletin",
                summary="Public channels are waiting on the next visible move.",
                source="public",
                urgency="low",
                turn=world.turn_number,
            )
        )
    items.sort(key=lambda item: (_urgency_rank(item.urgency), -item.turn, item.title))
    return items[:6]


def _nav_badges(
    scene: SceneView,
    action_groups: list[ActionSourceGroupView],
    backchannels: list[BackchannelThreadView],
) -> list[NavigationBadgeView]:
    proposal_count = sum(
        1
        for group in action_groups
        if group.source_type == "council"
        for card in group.cards
        if card.legal_now
    )
    return [
        NavigationBadgeView(room="control", label="Control Room"),
        NavigationBadgeView(
            room="advisors",
            label="Advisors Room",
            count=proposal_count,
            active=scene.has_pending_proposals,
            tone="amber" if proposal_count else "quiet",
        ),
        NavigationBadgeView(
            room="media",
            label="Media and Channels",
            count=len(backchannels),
            active=scene.has_new_backchannels,
            tone="red" if scene.has_new_backchannels else "quiet",
        ),
    ]


def _advisor_room_view(
    *,
    council: AdvisorCouncilView,
    council_read: list[str],
    action_groups: list[ActionSourceGroupView],
    agenda: AgendaView,
    conflicts: list[AgendaConflictView],
    latest_dialogue: AdvisorDialogueView | None,
) -> AdvisorRoomView:
    proposals_by_advisor: dict[str, ActionSourceGroupView] = {
        group.source_id: group
        for group in action_groups
        if group.source_type == "council"
    }
    figures: list[AdvisorFigureView] = []
    total = len(council.lines)
    left_count = (total + 1) // 2
    for index, line in enumerate(council.lines):
        side = "left" if index < left_count else "right"
        slot = index if side == "left" else index - left_count
        proposal = proposals_by_advisor.get(line.advisor_id)
        figures.append(
            AdvisorFigureView(
                advisor_id=line.advisor_id,
                name=line.name,
                portfolio=line.portfolio,
                trust=line.trust,
                urgency=line.urgency,
                caution=line.caution,
                current_belief=line.current_belief,
                latest_recommendation=line.latest_recommendation,
                latest_concern=line.latest_concern,
                asset_key=advisor_asset_key(line.advisor_id),
                side=side,
                slot=slot,
                has_proposals=bool(proposal and any(card.legal_now for card in proposal.cards)),
            )
        )
    advisor_names = {line.advisor_id: line.name for line in council.lines}
    proposals = [
        AdvisorProposalView(
            advisor_id=group.source_id,
            advisor_name=advisor_names.get(group.source_id, group.title),
            title=group.title,
            urgency=group.urgency,
            cards=group.cards,
        )
        for group in proposals_by_advisor.values()
    ]
    proposals.sort(key=lambda item: (_urgency_rank(item.urgency), item.advisor_name))
    return AdvisorRoomView(
        figures=figures,
        proposals=proposals,
        council_messages=council.summary,
        council_read=council_read,
        agenda=agenda,
        agenda_conflicts=conflicts,
        latest_dialogue=latest_dialogue,
    )


def _channel_thread_views(
    backchannels: list[BackchannelThreadView],
    session: GameSession,
) -> list[ChannelThreadView]:
    views: list[ChannelThreadView] = []
    for thread in backchannels:
        state = session.world.backchannel_threads.get(thread.thread_id)
        messages = [
            ChannelMessageView(
                message_id=record.record_id,
                sender=(
                    "You"
                    if record.sender_entity_id == session.player_id
                    else session.world.actors.get(record.sender_entity_id).name
                    if record.sender_entity_id in session.world.actors
                    else record.sender_entity_id.replace("_", " ").title()
                ),
                text=record.summary,
                turn=record.turn_number,
                is_player=record.sender_entity_id == session.player_id,
            )
            for record in (state.message_records[-6:] if state is not None else [])
        ]
        views.append(ChannelThreadView(
            thread_id=thread.thread_id,
            target_id=thread.target_id,
            counterpart=thread.counterpart,
            status=thread.status,
            expires_turn=thread.expires_turn,
            messages_remaining=thread.messages_remaining,
            trust_band=thread.trust_band,
            leak_risk_band=thread.leak_risk_band,
            latest=thread.latest,
            messages=messages,
            unread=bool(messages and not messages[-1].is_player and messages[-1].turn >= session.world.turn_number),
        ))
    return views


def _agenda_conflicts(
    session: GameSession,
    agenda: AgendaView,
) -> list[AgendaConflictView]:
    conflicts: list[AgendaConflictView] = []
    if session.plan_preview is not None and agenda.items:
        conflicts.append(
            AgendaConflictView(
                conflict_id="freeform-vs-agenda",
                title="Choose one command path",
                summary=(
                    "A freeform order preview and advisor-proposed agenda are both active. "
                    "Resolve one path before committing the turn."
                ),
                severity="blocking",
                related_item_ids=[item.agenda_item_id for item in agenda.items],
            )
        )
    for index, warning in enumerate(agenda.warnings):
        conflicts.append(
            AgendaConflictView(
                conflict_id=f"agenda-warning-{index}",
                title="Agenda warning",
                summary=warning,
                severity="warning",
                related_item_ids=[item.agenda_item_id for item in agenda.items],
            )
        )
    return conflicts


def _recent_result_lines(result: TurnResultView | None) -> list[str]:
    if result is None:
        return []
    lines: list[str] = []
    lines.extend(result.flash_events)
    lines.extend(result.media_headlines)
    lines.extend(result.consequences)
    lines.extend(result.advisor_reactions)
    lines.extend(result.npc_reactions)
    lines.extend(result.batch_warnings)
    if not lines and result.rendered_text:
        lines = [line for line in result.rendered_text.splitlines() if line.strip()]
    return lines[:10]


def _consequence_lines(report: TurnAftermathReport) -> list[str]:
    lines: list[str] = []
    for item in report.consequences:
        if item.source_package_id == "observed_turn_shift":
            lines.extend(f"Observed: {change}" for change in item.visible_metric_changes)
            if not item.visible_metric_changes:
                lines.append(f"Observed: {item.summary}")
            continue
        lines.append(f"Possible driver - {item.title}: {item.summary}")
        lines.extend(
            f"Reported pressure - {item.title}: {change}"
            for change in item.visible_metric_changes
        )
    return lines


def _settings_view() -> SettingsView:
    return SettingsView(
        fields=[
            SettingsFieldView(
                key="model",
                label="Model",
                value="Configured in llama_cpp.local.json",
                help="Runtime model editing is not enabled in this first room pass.",
            ),
            SettingsFieldView(
                key="token_budget",
                label="Token Budget",
                value="Backend default",
                help="A config-backed editor can be wired after the schema settles.",
            ),
            SettingsFieldView(
                key="pipeline",
                label="Pipeline",
                value="Local llama.cpp",
                help="Current session uses the local backend pipeline.",
            ),
        ]
    )


def _asset_manifest_view() -> AssetManifestView:
    return AssetManifestView(
        room_asset_keys=list(ROOM_ASSET_KEYS),
        advisor_asset_keys=list(ADVISOR_ASSET_KEYS),
        ui_asset_keys=list(UI_ASSET_KEYS),
    )


def _tension_level(world: WorldStateV2) -> int:
    tension_keys = (
        "escalation",
        "alarm",
        "anxiety",
        "incident",
        "risk",
        "nuclear",
        "command",
        "control",
        "readiness",
        "leak",
    )
    values = [
        value
        for metrics in (world.truth_metrics, world.public_metrics, world.hidden_clocks)
        for key, value in metrics.items()
        if any(term in key for term in tension_keys)
    ]
    score = max(values, default=0.0)
    if score >= 0.82:
        return 4
    if score >= 0.68:
        return 3
    if score >= 0.52:
        return 2
    if score >= 0.36:
        return 1
    return 0


def _timeline_urgency(entry: TimelineEntryView) -> str:
    text = f"{entry.title} {entry.summary}".lower()
    if any(term in text for term in ("nuclear", "attack", "war", "emergency")):
        return "critical"
    if any(term in text for term in ("warning", "alert", "contact", "leak")):
        return "high"
    if entry.turn <= 1:
        return "medium"
    return "low"


def _resource_views(world: WorldStateV2, player_id: str) -> list[ResourceView]:
    player = world.actors.get(player_id)
    if player is None:
        return []
    return [
        ResourceView(
            key=key,
            label=_resource_label(key),
            value=int(value),
            note=_resource_note(key),
        )
        for key, value in sorted(player.resources.items())
    ]


def _problem_views(briefing: TurnBriefing) -> list[ProblemView]:
    return [
        ProblemView(
            problem_id=problem.problem_id,
            title=problem.title,
            summary=problem.summary,
            urgency=problem.urgency,
            source=problem.source,
        )
        for problem in briefing.problems
    ]


def _pressure_views(briefing: TurnBriefing) -> list[PressureView]:
    return [
        PressureView(
            key=indicator.key,
            label=indicator.label,
            band=indicator.band,
            trend=indicator.trend,
            confidence=indicator.confidence,
            visible_summary=indicator.visible_summary,
        )
        for indicator in briefing.pressure_indicators
    ]


def _advisor_council_view(session: GameSession) -> AdvisorCouncilView:
    council = session.world.advisor_councils.get(session.player_id)
    if council is None:
        return AdvisorCouncilView()
    lines = []
    for advisor in council.advisors.values():
        belief = next(iter(advisor.beliefs.values()), None)
        lines.append(
            AdvisorLineView(
                advisor_id=advisor.advisor_id,
                name=advisor.name,
                portfolio=advisor.portfolio,
                trust=_trust_read(advisor.trust_player),
                urgency=_pressure_read(advisor.urgency),
                caution=_pressure_read(advisor.paranoia),
                current_belief=belief.summary if belief is not None else "",
                latest_recommendation=(
                    advisor.recent_recommendations[-1]
                    if advisor.recent_recommendations
                    else ""
                ),
                latest_concern=(
                    advisor.recent_embarrassments[-1]
                    if advisor.recent_embarrassments
                    else ""
                ),
                image_key=advisor_asset_key(advisor.advisor_id),
            )
        )
    summary: list[str] = []
    if session.world.advisor_update_history:
        summary = list(session.world.advisor_update_history[-1].summary)
    return AdvisorCouncilView(lines=lines, summary=summary)


def _action_groups(
    session: GameSession,
    briefing: TurnBriefing,
) -> list[ActionSourceGroupView]:
    groups: dict[tuple[str, str], ActionSourceGroupView] = {}
    for card in _event_choice_cards(session):
        _append_group_card(groups, card)
    for card in briefing.action_cards:
        view = _action_card_view(session, card)
        _append_group_card(groups, view)

    ordered = list(groups.values())
    for group in ordered:
        group.cards.sort(key=lambda item: (_urgency_rank(item.urgency), not item.legal_now, item.title))
        group.urgency = group.cards[0].urgency if group.cards else "medium"
    ordered.sort(key=lambda group: (_group_rank(group.source_type, group.title), _urgency_rank(group.urgency), group.title))
    return ordered


def _event_choice_cards(session: GameSession) -> list[ActionCardView]:
    cards: list[ActionCardView] = []
    for choice in _active_event_choices(session.world, session.player_id):
        for option in choice.options:
            card_id = event_choice_card_id(choice.choice_id, option.option_id)
            package = session.safe_package_for_card(card_id)
            cards.append(
                ActionCardView(
                    card_id=card_id,
                    source_type="event",
                    source_id=choice.event_id,
                    title=option.label,
                    category="Event Choice",
                    urgency="critical",
                    legal_now=package is not None,
                    locked_reason="" if package is not None else "Choice is no longer available.",
                    cost_summary=(
                        "normal action bandwidth"
                        if option.consumes_normal_action_budget
                        else "event-only bandwidth"
                    ),
                    expected_pressure_summary=option.summary,
                    risk_summary="turn-significant response",
                    prompt_hint=choice.prompt,
                    action_id=option.action_id,
                    capability_id=option.capability_id,
                    default_action_package=_package_dump(package),
                    debug_rationale=(
                        f"pending event choice {choice.choice_id}:{option.option_id}"
                    ),
                )
            )
    return cards


def _action_card_view(session: GameSession, card: ActionCard) -> ActionCardView:
    card_id = action_card_id(card)
    source_type, source_id, source_title = _source_for_action_card(card)
    urgency = _card_urgency(card)
    package = session.safe_package_for_card(card_id) if card.legal_now else None
    return ActionCardView(
        card_id=card_id,
        source_type=source_type,
        source_id=source_id,
        title=card.title,
        category=card.category,
        urgency=urgency,
        legal_now=card.legal_now and package is not None,
        locked_reason=card.locked_reason,
        cost_summary=card.cost_summary,
        expected_pressure_summary=card.expected_pressure_summary,
        risk_summary=card.risk_summary,
        prompt_hint=card.prompt_hint,
        action_id=card.action_id,
        capability_id=card.capability_id,
        default_action_package=_package_dump(package),
        debug_rationale=f"{source_title}; generated from current briefing card",
    )


def _agenda_view(session: GameSession) -> AgendaView:
    items: list[AgendaItemView] = []
    warnings: list[str] = []
    for item in session.agenda_items:
        validation = session.validate_package(item.package)
        items.append(
            AgendaItemView(
                agenda_item_id=item.agenda_item_id,
                card_id=item.card_id,
                title=item.title,
                category=item.category,
                source_title=item.source_title,
                action_id=item.package.action_id,
                capability_id=item.package.capability_id,
                validation_errors=list(validation.errors),
                validation_warnings=list(validation.warnings),
            )
        )
        warnings.extend(validation.errors)
    if len(items) > session.action_budget:
        warnings.append(
            f"Agenda has {len(items)} actions; normal bandwidth is {session.action_budget}."
        )
    remaining = max(0, session.action_budget - len(items))
    return AgendaView(
        items=items,
        max_actions=session.action_budget,
        remaining_actions=remaining,
        warnings=warnings,
        can_commit=bool(items) and not warnings and not session.world.accepted_ending_id,
    )


def _plan_preview_view(session: GameSession) -> PlanPreviewView | None:
    preview = session.plan_preview
    if preview is None:
        return None
    return PlanPreviewView(
        turn_number=preview.turn_number,
        player_intent=preview.player_intent,
        is_committable=preview.is_committable,
        actions=[
            PlanPreviewActionView(
                title=_package_title(session, package),
                intent_summary=package.intent_summary,
                action_id=package.action_id,
                capability_id=package.capability_id,
                target_ids=list(package.target_ids),
                channel=package.channel.value,
            )
            for package in preview.compilation.action_packages
        ],
        warnings=[
            warning.message
            for warning in preview.batch_validation_report.warnings
            if warning.player_visible
        ],
        errors=list(preview.compilation.errors),
        notes=list(preview.compilation.notes[:6]),
        known_pending_actions=list(preview.known_pending_actions),
        resource_pressure=[_humanize_plan_line(item) for item in preview.resource_pressure],
        open_backchannel_constraints=list(preview.open_backchannel_constraints),
        recent_event_context=list(preview.recent_event_context),
        visible_flash_event_risks=list(preview.visible_flash_event_risks),
        known_consequences=list(preview.known_consequences),
        compiled_intents=list(preview.compilation.compiled_intents),
        rejected_intents=list(preview.compilation.rejected_intents),
        unprocessed_intents=list(preview.compilation.unprocessed_intents),
        action_slots_used=len(preview.compilation.action_packages),
        action_slots_available=preview.compilation.action_budget,
        rendered_text=session.plan_preview_rendered,
    )


def _turn_result_view(session: GameSession) -> TurnResultView | None:
    if session.latest_aftermath_report is None and not session.latest_result_rendered:
        return None
    if session.latest_aftermath_report is None:
        return TurnResultView(
            turn_number=session.world.turn_number,
            rendered_text=session.latest_result_rendered,
        )
    return build_turn_result_view(
        session.latest_aftermath_report,
        rendered_text=session.latest_result_rendered,
    )


def _advisor_dialogue_view(session: GameSession) -> AdvisorDialogueView | None:
    response = session.latest_advisor_response
    if response is None:
        return None
    return AdvisorDialogueView(
        question=session.latest_advisor_question,
        answer=response.answer,
        council_summary=response.council_summary,
        advisor_views=[
            f"{view.advisor_name}: {view.stance}. {view.reasoning}"
            for view in response.advisor_views
        ],
        risk_warnings=list(response.risk_warnings),
        suggested_moves=list(response.suggested_capability_ids or response.suggested_action_ids),
        information_gaps=list(response.information_gaps),
        visible_context_limits=list(response.visible_context_limits),
    )


def _backchannel_views(world: WorldStateV2, player_id: str) -> list[BackchannelThreadView]:
    views: list[BackchannelThreadView] = []
    for thread in world.backchannel_threads.values():
        if player_id not in thread.participant_entity_ids:
            continue
        if thread.status != BackchannelThreadStatus.OPEN:
            continue
        if thread.expires_turn < world.turn_number:
            continue
        counterpart_ids = [
            entity_id
            for entity_id in thread.participant_entity_ids
            if entity_id != player_id
        ]
        counterpart_names = [
            world.actors[entity_id].name
            for entity_id in counterpart_ids
            if entity_id in world.actors
        ]
        opened_by = _thread_opened_by(world, thread, player_id)
        latest_report = thread.message_records[-1].summary if thread.message_records else ""
        latest = f"Opened by {opened_by}."
        if latest_report:
            latest = f"{latest} Latest reported exchange: {latest_report}"
        views.append(
            BackchannelThreadView(
                thread_id=thread.thread_id,
                target_id=counterpart_ids[0] if counterpart_ids else "",
                counterpart=", ".join(counterpart_names or counterpart_ids) or "Unknown",
                status=thread.status.value,
                expires_turn=thread.expires_turn,
                messages_remaining=thread.player_messages_remaining_for_turn(
                    world.turn_number
                ),
                trust_band=_trust_read(thread.trust_level),
                leak_risk_band=_pressure_read(thread.leak_risk),
                latest=latest,
            )
        )
    views.sort(key=lambda item: (item.expires_turn, item.counterpart))
    return views


def _thread_opened_by(
    world: WorldStateV2,
    thread: object,
    player_id: str,
) -> str:
    sender = str(getattr(thread, "metadata", {}).get("opened_by") or "")
    records = getattr(thread, "message_records", [])
    if not sender and records:
        sender = records[0].sender_entity_id
    if sender == player_id:
        return "you"
    actor = world.actors.get(sender)
    return actor.name if actor is not None else (sender or "an unclear source")


def _pending_event_choice_views(
    world: WorldStateV2,
    player_id: str,
) -> list[PendingEventChoiceView]:
    views: list[PendingEventChoiceView] = []
    for choice in _active_event_choices(world, player_id):
        views.append(
            PendingEventChoiceView(
                choice_id=choice.choice_id,
                event_id=choice.event_id,
                title=choice.title,
                prompt=choice.prompt,
                expires_turn=choice.expires_turn,
                options=[
                    PendingEventOptionView(
                        option_id=option.option_id,
                        label=option.label,
                        summary=option.summary,
                        card_id=event_choice_card_id(choice.choice_id, option.option_id),
                        consumes_normal_action_budget=option.consumes_normal_action_budget,
                    )
                    for option in choice.options
                ],
            )
        )
    return views


def _ending_offer_views(world: WorldStateV2, player_id: str) -> list[EndingOfferView]:
    return [
        EndingOfferView(
            offer_id=offer.offer_id,
            ending_id=offer.ending_id,
            title=offer.title,
            summary=offer.summary,
        )
        for offer in active_ending_offers(world, player_entity_id=player_id)
    ]


def _timeline_views(world: WorldStateV2, player_id: str) -> list[TimelineEntryView]:
    entries: list[TimelineEntry] = []
    entries.extend(world.public_timeline.latest(8))
    player_timeline = world.entity_timelines.get(player_id)
    if player_timeline is not None:
        entries.extend(player_timeline.latest(8))
    entries.sort(key=lambda item: (item.turn, item.created_at))
    return [
        TimelineEntryView(
            entry_id=entry.entry_id,
            turn=entry.turn,
            scope=entry.scope.value,
            title=entry.title,
            summary=entry.summary,
            source=entry.source,
            created_at=entry.created_at,
        )
        for entry in entries[-50:]
    ]


def _debug_view(session: GameSession) -> DebugView:
    world = session.world
    calls = getattr(session.llm_client, "calls", [])
    return DebugView(
        world_schema_version=world.schema_version,
        truth_metrics=dict(sorted(world.truth_metrics.items())),
        public_metrics=dict(sorted(world.public_metrics.items())),
        hidden_clocks=dict(sorted(world.hidden_clocks.items())),
        raw_actor_ids=sorted(world.actors),
        pending_action_ids=[package.mechanical_id for package in world.pending_actions],
        pending_signal_count=len(world.pending_signals),
        llm_call_count=len(calls) if isinstance(calls, list) else 0,
        latest_debug_text=session.latest_debug_text,
    )


def _append_group_card(
    groups: dict[tuple[str, str], ActionSourceGroupView],
    card: ActionCardView,
) -> None:
    key = (card.source_type, card.source_id)
    if key not in groups:
        groups[key] = ActionSourceGroupView(
            source_type=card.source_type,
            source_id=card.source_id,
            title=_source_title(card.source_type, card.source_id),
        )
    groups[key].cards.append(card)


def _source_for_action_card(card: ActionCard) -> tuple[str, str, str]:
    mechanical_id = card.capability_id or card.action_id
    lowered = mechanical_id.lower()
    category = card.category.lower()
    if "direct_kremlin_message" in lowered or "jupiter" in lowered:
        return "backchannel", "backchannels", "Backchannels"
    if "backchannel" in lowered:
        return "council", "state", "Council: State"
    if category == "military":
        return "council", "defense", "Council: Defense"
    if category == "intelligence":
        return "council", "intelligence", "Council: Intelligence"
    if category in {"information", "domestic"} or "public" in lowered:
        return "council", "political", "Council: Political"
    if category == "diplomatic":
        return "council", "state", "Council: State"
    return "scenario", "scenario", "Scenario"


def _source_title(source_type: str, source_id: str) -> str:
    if source_type == "event":
        return "Situation"
    if source_type == "backchannel":
        return "Backchannels"
    if source_type == "council":
        return {
            "state": "Council: State",
            "defense": "Council: Defense",
            "intelligence": "Council: Intelligence",
            "political": "Council: Political",
            "legal_un": "Council: Legal/UN",
        }.get(source_id, f"Council: {source_id.replace('_', ' ').title()}")
    return source_id.replace("_", " ").title()


def _card_urgency(card: ActionCard) -> str:
    if not card.legal_now:
        return "low"
    risk = card.risk_summary.lower()
    expected = card.expected_pressure_summary.lower()
    title = card.title.lower()
    if "severe" in risk or "high escalation" in risk or "air strike" in title:
        return "critical"
    if "incident" in expected or "off-ramp" in expected or "readiness" in title:
        return "high"
    return "medium"


def _active_event_choices(
    world: WorldStateV2,
    player_id: str,
) -> list[ScenarioEventChoiceRecord]:
    return [
        choice
        for choice in world.pending_event_choices
        if choice.active_for(world.turn_number, player_id)
    ]


def _package_dump(package: ActionPackage | None) -> dict[str, Any] | None:
    if package is None:
        return None
    return package.model_dump(mode="json")


def _package_title(session: GameSession, package: ActionPackage) -> str:
    definition, errors = ActionResolver(
        session.scenario.action_catalog,
        session.scenario.capabilities,
    ).resolve_package(package)
    return definition.title if definition is not None and not errors else package.mechanical_id.replace("_", " ").title()


def _humanize_plan_line(line: str) -> str:
    for key in (
        "political_capital",
        "military_readiness",
        "alliance_credit",
        "intelligence_focus",
        "diplomatic_flexibility",
        "air_defense_control",
    ):
        line = line.replace(key, _resource_label(key))
    return line


def _group_rank(source_type: str, title: str) -> int:
    if source_type == "event":
        return 0
    if source_type == "backchannel":
        return 1
    if "State" in title:
        return 2
    if "Defense" in title:
        return 3
    if "Intelligence" in title:
        return 4
    if "Political" in title:
        return 5
    return 9


def _urgency_rank(urgency: str) -> int:
    return {
        "critical": 0,
        "urgent": 1,
        "high": 2,
        "medium": 3,
        "low": 4,
    }.get(urgency, 5)


def _resource_label(key: str) -> str:
    return {
        "political_capital": "Political Capital",
        "military_readiness": "Military Readiness",
        "alliance_credit": "Alliance Credit",
        "intelligence_focus": "Intelligence Focus",
        "diplomatic_flexibility": "Diplomatic Flexibility",
        "air_defense_control": "Air Defense Control",
    }.get(key, key.replace("_", " ").title())


def _resource_note(key: str) -> str:
    return {
        "political_capital": "Room for visible commitments.",
        "military_readiness": "Available readiness before posture costs bite.",
        "alliance_credit": "Diplomatic trust with allies.",
        "intelligence_focus": "Attention available for reconnaissance.",
        "diplomatic_flexibility": "Opponent room for private compromise.",
        "air_defense_control": "Local restraint around air defense.",
    }.get(key, "")


def _trust_read(value: float) -> str:
    if value >= 0.72:
        return "strong"
    if value >= 0.55:
        return "steady"
    if value >= 0.38:
        return "fragile"
    return "strained"


def _pressure_read(value: float) -> str:
    if value >= 0.75:
        return "high"
    if value >= 0.55:
        return "rising"
    if value >= 0.35:
        return "guarded"
    return "low"
