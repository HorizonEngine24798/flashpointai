export type ScenarioView = {
  scenario_id: string;
  title: string;
  historical_period: string;
  description: string;
  player_entity_id: string;
};

export type TurnView = {
  turn_number: number;
  time_label: string;
  situation_summary: string;
  accepted_ending_id: string;
  final_summary: string;
  is_concluded: boolean;
};

export type ResourceView = {
  key: string;
  label: string;
  value: number;
  note: string;
};

export type ProblemView = {
  problem_id: string;
  title: string;
  summary: string;
  urgency: string;
  source: string;
};

export type PressureView = {
  key: string;
  label: string;
  band: string;
  trend: string;
  confidence: string;
  visible_summary: string;
};

export type AdvisorLineView = {
  advisor_id: string;
  name: string;
  portfolio: string;
  trust: string;
  urgency: string;
  caution: string;
  current_belief: string;
  latest_recommendation: string;
  latest_concern: string;
  image_key: string;
};

export type AdvisorCouncilView = {
  lines: AdvisorLineView[];
  summary: string[];
};

export type ActionCardView = {
  card_id: string;
  source_type: string;
  source_id: string;
  title: string;
  category: string;
  urgency: string;
  legal_now: boolean;
  locked_reason: string;
  cost_summary: string;
  expected_pressure_summary: string;
  risk_summary: string;
  prompt_hint: string;
  action_id: string;
  capability_id: string | null;
  default_action_package: Record<string, unknown> | null;
  debug_rationale: string;
};

export type ActionSourceGroupView = {
  source_type: string;
  source_id: string;
  title: string;
  urgency: string;
  cards: ActionCardView[];
};

export type AgendaItemView = {
  agenda_item_id: string;
  card_id: string;
  title: string;
  category: string;
  source_title: string;
  action_id: string;
  capability_id: string | null;
  validation_errors: string[];
  validation_warnings: string[];
};

export type AgendaView = {
  items: AgendaItemView[];
  max_actions: number;
  remaining_actions: number;
  warnings: string[];
  can_commit: boolean;
};

export type PlanPreviewView = {
  turn_number: number;
  player_intent: string;
  is_committable: boolean;
  actions: {
    title: string;
    intent_summary: string;
    action_id: string;
    capability_id: string | null;
    target_ids: string[];
    channel: string;
  }[];
  warnings: string[];
  errors: string[];
  notes: string[];
  known_pending_actions: string[];
  resource_pressure: string[];
  open_backchannel_constraints: string[];
  recent_event_context: string[];
  visible_flash_event_risks: string[];
  known_consequences: string[];
  compiled_intents: string[];
  rejected_intents: string[];
  unprocessed_intents: string[];
  action_slots_used: number;
  action_slots_available: number;
  rendered_text: string;
} | null;

export type TurnResultView = {
  turn_number: number;
  accepted_actions: string[];
  resolved_actions: string[];
  rejected_actions: string[];
  resource_blocked_actions: string[];
  scheduled_actions: string[];
  action_results: string[];
  chief_updates: string[];
  critical_warnings: string[];
  batch_warnings: string[];
  flash_events: string[];
  media_headlines: string[];
  consequences: string[];
  pressure_updates: string[];
  advisor_reactions: string[];
  npc_reactions: string[];
  new_problems: ProblemView[];
  rendered_text: string;
} | null;

export type AdvisorDialogueView = {
  question: string;
  answer: string;
  council_summary: string;
  advisor_views: string[];
  risk_warnings: string[];
  suggested_moves: string[];
  information_gaps: string[];
  visible_context_limits: string[];
} | null;

export type BackchannelThreadView = {
  thread_id: string;
  target_id: string;
  counterpart: string;
  status: string;
  expires_turn: number;
  messages_remaining: number;
  trust_band: string;
  leak_risk_band: string;
  latest: string;
};

export type ChannelMessageView = {
  message_id: string;
  sender: string;
  text: string;
  turn: number;
  is_player: boolean;
};

export type PendingEventChoiceView = {
  choice_id: string;
  event_id: string;
  title: string;
  prompt: string;
  expires_turn: number | null;
  options: {
    option_id: string;
    label: string;
    summary: string;
    card_id: string;
    consumes_normal_action_budget: boolean;
  }[];
};

export type EndingOfferView = {
  offer_id: string;
  ending_id: string;
  title: string;
  summary: string;
};

export type SaveSummaryView = {
  save_id: string;
  display_name: string;
  scenario_id: string;
  scenario_title: string;
  turn_number: number;
  time_label: string;
  saved_at: string | null;
  player_entity_id: string;
  compatible: boolean;
  compatibility_error: string;
};

export type TimelineEntryView = {
  entry_id: string;
  turn: number;
  scope: string;
  title: string;
  summary: string;
  source: string;
  created_at: string;
};

export type DebugView = {
  world_schema_version: string;
  truth_metrics: Record<string, number>;
  public_metrics: Record<string, number>;
  hidden_clocks: Record<string, number>;
  raw_actor_ids: string[];
  pending_action_ids: string[];
  pending_signal_count: number;
  llm_call_count: number;
  latest_debug_text: string;
} | null;

export type SceneView = {
  tension_level: number;
  room_asset_key: string;
  lighting_band: string;
  has_new_results: boolean;
  has_new_backchannels: boolean;
  has_pending_proposals: boolean;
};

export type StartMenuView = {
  title: string;
  subtitle: string;
  continue_available: boolean;
  recent_save: SaveSummaryView | null;
};

export type ScenarioOptionView = {
  scenario_id: string;
  title: string;
  historical_period: string;
  description: string;
  thumbnail_asset_key: string;
};

export type BreakingNewsItemView = {
  item_id: string;
  title: string;
  summary: string;
  source: string;
  urgency: string;
  turn: number;
  is_new: boolean;
};

export type NavigationBadgeView = {
  room: "control" | "advisors" | "media" | string;
  label: string;
  count: number;
  active: boolean;
  tone: string;
};

export type AgendaConflictView = {
  conflict_id: string;
  title: string;
  summary: string;
  severity: string;
  related_item_ids: string[];
};

export type ChiefPlanView = {
  plan_id: string;
  objectives: string[];
  rationale: string;
  recommended_actions: string[];
  latest_assessment: string;
};

export type ControlRoomView = {
  situation_summary: string;
  open_problems: ProblemView[];
  recent_results: string[];
  latest_result: TurnResultView;
  critical_warnings: string[];
  chief_plan: ChiefPlanView | null;
  pressure: PressureView[];
  resources: ResourceView[];
  agenda: AgendaView;
  agenda_conflicts: AgendaConflictView[];
};

export type AdvisorFigureView = {
  advisor_id: string;
  name: string;
  portfolio: string;
  trust: string;
  urgency: string;
  caution: string;
  current_belief: string;
  latest_recommendation: string;
  latest_concern: string;
  asset_key: string;
  side: "left" | "right" | string;
  slot: number;
  has_proposals: boolean;
};

export type AdvisorProposalView = {
  advisor_id: string;
  advisor_name: string;
  title: string;
  urgency: string;
  cards: ActionCardView[];
};

export type AdvisorRoomView = {
  figures: AdvisorFigureView[];
  proposals: AdvisorProposalView[];
  council_messages: string[];
  council_read: string[];
  agenda: AgendaView;
  agenda_conflicts: AgendaConflictView[];
  latest_dialogue: AdvisorDialogueView;
};

export type ChannelThreadView = {
  thread_id: string;
  target_id: string;
  counterpart: string;
  status: string;
  expires_turn: number;
  messages_remaining: number;
  trust_band: string;
  leak_risk_band: string;
  latest: string;
  messages: ChannelMessageView[];
  unread: boolean;
};

export type MediaRoomView = {
  news_items: BreakingNewsItemView[];
  timeline: TimelineEntryView[];
  channel_threads: ChannelThreadView[];
  has_unread: boolean;
};

export type SettingsFieldView = {
  key: string;
  label: string;
  value: string;
  help: string;
  disabled: boolean;
};

export type SettingsView = {
  config_path: string;
  fields: SettingsFieldView[];
  save_enabled: boolean;
  load_enabled: boolean;
};

export type AssetManifestView = {
  room_asset_keys: string[];
  advisor_asset_keys: string[];
  ui_asset_keys: string[];
};

export type GameView = {
  scenario: ScenarioView;
  turn: TurnView;
  scene: SceneView;
  start_menu: StartMenuView;
  scenario_options: ScenarioOptionView[];
  ticker: BreakingNewsItemView[];
  nav_badges: NavigationBadgeView[];
  control_room: ControlRoomView;
  advisor_room: AdvisorRoomView;
  media_room: MediaRoomView;
  settings: SettingsView;
  asset_manifest: AssetManifestView;
  agenda: AgendaView;
  plan_preview: PlanPreviewView;
  pending_event_choices: PendingEventChoiceView[];
  ending_offers: EndingOfferView[];
  saves: SaveSummaryView[];
  debug: DebugView;
};
