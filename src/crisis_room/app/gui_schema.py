from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


ACTION_CARD_PREFIX = "action"
EVENT_CHOICE_CARD_PREFIX = "event_choice"


class ScenarioView(BaseModel):
    scenario_id: str
    title: str
    historical_period: str = ""
    description: str = ""
    player_entity_id: str


class TurnView(BaseModel):
    turn_number: int
    time_label: str = ""
    situation_summary: str = ""
    accepted_ending_id: str = ""
    final_summary: str = ""
    is_concluded: bool = False


class ResourceView(BaseModel):
    key: str
    label: str
    value: int
    note: str = ""


class ProblemView(BaseModel):
    problem_id: str
    title: str
    summary: str
    urgency: str
    source: str


class PressureView(BaseModel):
    key: str
    label: str
    band: str
    trend: str
    confidence: str
    visible_summary: str = ""


class AdvisorLineView(BaseModel):
    advisor_id: str
    name: str
    portfolio: str
    trust: str
    urgency: str
    caution: str
    current_belief: str = ""
    latest_recommendation: str = ""
    latest_concern: str = ""
    image_key: str = ""


class AdvisorCouncilView(BaseModel):
    lines: list[AdvisorLineView] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ActionCardView(BaseModel):
    card_id: str
    source_type: str
    source_id: str
    title: str
    category: str
    urgency: str
    legal_now: bool
    locked_reason: str = ""
    cost_summary: str = ""
    expected_pressure_summary: str = ""
    risk_summary: str = ""
    prompt_hint: str = ""
    action_id: str
    capability_id: str | None = None
    default_action_package: dict[str, Any] | None = None
    debug_rationale: str = ""


class ActionSourceGroupView(BaseModel):
    source_type: str
    source_id: str
    title: str
    urgency: str = "medium"
    cards: list[ActionCardView] = Field(default_factory=list)


class AgendaItemView(BaseModel):
    agenda_item_id: str
    card_id: str
    title: str
    category: str
    source_title: str
    action_id: str
    capability_id: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class AgendaView(BaseModel):
    items: list[AgendaItemView] = Field(default_factory=list)
    max_actions: int
    remaining_actions: int
    warnings: list[str] = Field(default_factory=list)
    can_commit: bool = False


class PlanPreviewActionView(BaseModel):
    title: str
    intent_summary: str = ""
    action_id: str
    capability_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: str = ""


class PlanPreviewView(BaseModel):
    turn_number: int
    player_intent: str
    is_committable: bool
    actions: list[PlanPreviewActionView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    known_pending_actions: list[str] = Field(default_factory=list)
    resource_pressure: list[str] = Field(default_factory=list)
    open_backchannel_constraints: list[str] = Field(default_factory=list)
    recent_event_context: list[str] = Field(default_factory=list)
    visible_flash_event_risks: list[str] = Field(default_factory=list)
    known_consequences: list[str] = Field(default_factory=list)
    compiled_intents: list[str] = Field(default_factory=list)
    rejected_intents: list[str] = Field(default_factory=list)
    unprocessed_intents: list[str] = Field(default_factory=list)
    action_slots_used: int = 0
    action_slots_available: int = 0
    rendered_text: str = ""


class TurnResultView(BaseModel):
    turn_number: int
    accepted_actions: list[str] = Field(default_factory=list)
    resolved_actions: list[str] = Field(default_factory=list)
    rejected_actions: list[str] = Field(default_factory=list)
    resource_blocked_actions: list[str] = Field(default_factory=list)
    scheduled_actions: list[str] = Field(default_factory=list)
    critical_warnings: list[str] = Field(default_factory=list)
    batch_warnings: list[str] = Field(default_factory=list)
    flash_events: list[str] = Field(default_factory=list)
    media_headlines: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    pressure_updates: list[str] = Field(default_factory=list)
    advisor_reactions: list[str] = Field(default_factory=list)
    npc_reactions: list[str] = Field(default_factory=list)
    new_problems: list[ProblemView] = Field(default_factory=list)
    rendered_text: str = ""


class AdvisorDialogueView(BaseModel):
    question: str
    answer: str
    council_summary: str = ""
    advisor_views: list[str] = Field(default_factory=list)
    risk_warnings: list[str] = Field(default_factory=list)
    suggested_moves: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    visible_context_limits: list[str] = Field(default_factory=list)


class BackchannelThreadView(BaseModel):
    thread_id: str
    target_id: str
    counterpart: str
    status: str
    expires_turn: int
    messages_remaining: int
    trust_band: str
    leak_risk_band: str
    latest: str = ""


class ChannelMessageView(BaseModel):
    message_id: str
    sender: str
    text: str
    turn: int
    is_player: bool = False


class PendingEventOptionView(BaseModel):
    option_id: str
    label: str
    summary: str
    card_id: str
    consumes_normal_action_budget: bool = True


class PendingEventChoiceView(BaseModel):
    choice_id: str
    event_id: str
    title: str
    prompt: str
    expires_turn: int | None = None
    options: list[PendingEventOptionView] = Field(default_factory=list)


class EndingOfferView(BaseModel):
    offer_id: str
    ending_id: str
    title: str
    summary: str


class TimelineEntryView(BaseModel):
    entry_id: str
    turn: int
    scope: str
    title: str
    summary: str
    source: str
    created_at: datetime


class SaveSummaryView(BaseModel):
    save_id: str
    display_name: str
    scenario_id: str
    scenario_title: str = ""
    turn_number: int = 0
    time_label: str = ""
    saved_at: datetime | None = None
    player_entity_id: str = ""
    compatible: bool = True
    compatibility_error: str = ""


class DebugView(BaseModel):
    world_schema_version: str
    truth_metrics: dict[str, float] = Field(default_factory=dict)
    public_metrics: dict[str, float] = Field(default_factory=dict)
    hidden_clocks: dict[str, float] = Field(default_factory=dict)
    raw_actor_ids: list[str] = Field(default_factory=list)
    pending_action_ids: list[str] = Field(default_factory=list)
    pending_signal_count: int = 0
    llm_call_count: int = 0
    latest_debug_text: str = ""


class SceneView(BaseModel):
    tension_level: int = 0
    room_asset_key: str = "rooms/control_tension_0"
    lighting_band: str = "cold"
    has_new_results: bool = False
    has_new_backchannels: bool = False
    has_pending_proposals: bool = False


class StartMenuView(BaseModel):
    title: str = "The Crisis Room"
    subtitle: str = "where good intentions go to die"
    continue_available: bool = False
    recent_save: SaveSummaryView | None = None


class ScenarioOptionView(BaseModel):
    scenario_id: str
    title: str
    historical_period: str = ""
    description: str = ""
    thumbnail_asset_key: str = "scenarios/cuba_missile_crisis"


class BreakingNewsItemView(BaseModel):
    item_id: str
    title: str
    summary: str
    source: str = "public"
    urgency: str = "medium"
    turn: int = 0
    is_new: bool = False


class NavigationBadgeView(BaseModel):
    room: str
    label: str
    count: int = 0
    active: bool = False
    tone: str = "quiet"


class AgendaConflictView(BaseModel):
    conflict_id: str
    title: str
    summary: str
    severity: str = "warning"
    related_item_ids: list[str] = Field(default_factory=list)


class ControlRoomView(BaseModel):
    situation_summary: str = ""
    open_problems: list[ProblemView] = Field(default_factory=list)
    recent_results: list[str] = Field(default_factory=list)
    latest_result: TurnResultView | None = None
    critical_warnings: list[str] = Field(default_factory=list)
    pressure: list[PressureView] = Field(default_factory=list)
    resources: list[ResourceView] = Field(default_factory=list)
    agenda: AgendaView
    agenda_conflicts: list[AgendaConflictView] = Field(default_factory=list)


class AdvisorFigureView(BaseModel):
    advisor_id: str
    name: str
    portfolio: str
    trust: str
    urgency: str
    caution: str
    current_belief: str = ""
    latest_recommendation: str = ""
    latest_concern: str = ""
    asset_key: str = "advisors/shadowed_unknown"
    side: str = "left"
    slot: int = 0
    has_proposals: bool = False


class AdvisorProposalView(BaseModel):
    advisor_id: str
    advisor_name: str
    title: str
    urgency: str = "medium"
    cards: list[ActionCardView] = Field(default_factory=list)


class AdvisorRoomView(BaseModel):
    figures: list[AdvisorFigureView] = Field(default_factory=list)
    proposals: list[AdvisorProposalView] = Field(default_factory=list)
    council_messages: list[str] = Field(default_factory=list)
    council_read: list[str] = Field(default_factory=list)
    agenda: AgendaView
    agenda_conflicts: list[AgendaConflictView] = Field(default_factory=list)
    latest_dialogue: AdvisorDialogueView | None = None


class ChannelThreadView(BaseModel):
    thread_id: str
    target_id: str
    counterpart: str
    status: str
    expires_turn: int
    messages_remaining: int
    trust_band: str
    leak_risk_band: str
    latest: str = ""
    messages: list[ChannelMessageView] = Field(default_factory=list)
    unread: bool = False


class MediaRoomView(BaseModel):
    news_items: list[BreakingNewsItemView] = Field(default_factory=list)
    timeline: list[TimelineEntryView] = Field(default_factory=list)
    channel_threads: list[ChannelThreadView] = Field(default_factory=list)
    has_unread: bool = False


class SettingsFieldView(BaseModel):
    key: str
    label: str
    value: str = ""
    help: str = ""
    disabled: bool = True


class SettingsView(BaseModel):
    config_path: str = "config/llama_cpp.local.json"
    fields: list[SettingsFieldView] = Field(default_factory=list)
    save_enabled: bool = True
    load_enabled: bool = True


class AssetManifestView(BaseModel):
    room_asset_keys: list[str] = Field(default_factory=list)
    advisor_asset_keys: list[str] = Field(default_factory=list)
    ui_asset_keys: list[str] = Field(default_factory=list)


class GameView(BaseModel):
    scenario: ScenarioView
    turn: TurnView
    scene: SceneView = Field(default_factory=SceneView)
    start_menu: StartMenuView = Field(default_factory=StartMenuView)
    scenario_options: list[ScenarioOptionView] = Field(default_factory=list)
    ticker: list[BreakingNewsItemView] = Field(default_factory=list)
    nav_badges: list[NavigationBadgeView] = Field(default_factory=list)
    control_room: ControlRoomView
    advisor_room: AdvisorRoomView
    media_room: MediaRoomView
    settings: SettingsView = Field(default_factory=SettingsView)
    asset_manifest: AssetManifestView = Field(default_factory=AssetManifestView)
    agenda: AgendaView
    plan_preview: PlanPreviewView | None = None
    pending_event_choices: list[PendingEventChoiceView] = Field(default_factory=list)
    ending_offers: list[EndingOfferView] = Field(default_factory=list)
    saves: list[SaveSummaryView] = Field(default_factory=list)
    debug: DebugView | None = None


def action_card_id(card: Any) -> str:
    return f"{ACTION_CARD_PREFIX}|{card.capability_id or card.action_id}"


def event_choice_card_id(choice_id: str, option_id: str) -> str:
    return f"{EVENT_CHOICE_CARD_PREFIX}|{choice_id}|{option_id}"
