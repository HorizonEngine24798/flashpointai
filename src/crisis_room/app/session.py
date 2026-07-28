from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from crisis_room.agents.dialogue_engine import DialogueEngineAgent
from crisis_room.agents.gamemaster import GamemasterCompilation
from crisis_room.app.backchannels import (
    prepare_backchannel_message,
    render_backchannel_direct_message_result,
    resolve_backchannel_target,
    send_backchannel_message,
)
from crisis_room.app.debug_sessions import DebugSessionRecorder
from crisis_room.app.gui_builder import build_game_view
from crisis_room.app.gui_schema import (
    ACTION_CARD_PREFIX,
    EVENT_CHOICE_CARD_PREFIX,
    GameView,
    SaveSummaryView,
    action_card_id,
    event_choice_card_id,
)
from crisis_room.app.planning import (
    PlayerPlanPreview,
    build_player_plan_preview,
    render_player_plan_preview,
)
from crisis_room.app.presentation import (
    TurnAftermathReport,
    TurnBriefing,
    build_turn_briefing,
    render_aftermath_report,
)
from crisis_room.app.runtime_helpers import (
    format_advisor_retry_error,
    format_runtime_error,
    llm_call_count,
    llm_call_records,
)
from crisis_room.app.turn_orchestrator import (
    RecoverableAdvisorDialogueError,
    RecoverablePlayerActionError,
    TurnOrchestrator,
)
from crisis_room.config.gameplay import HARD_ACTION_BUDGET, NORMAL_ACTION_BUDGET
from crisis_room.config.settings import load_settings
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ActionResolver,
)
from crisis_room.engine.action_matching import (
    actor_allowed,
    default_channel,
    default_targets,
)
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.diagnostics import LlamaCppJSONError
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.task_contracts import AdvisorCouncilResponse
from crisis_room.scenario.endings import accept_ending_offer, reject_ending_offer
from crisis_room.scenario.event_choices import build_event_choice_action
from crisis_room.scenario.loader import DEFAULT_SCENARIO_ID, load_scenario
from crisis_room.scenario.schema import Scenario
from crisis_room.state.saves import (
    build_playable_save_record,
    load_playable_session,
    pending_plan_matches_world,
    restore_pending_plan,
)
from crisis_room.state.world import WorldStateV2


@dataclass
class AgendaSelection:
    agenda_item_id: str
    card_id: str
    title: str
    category: str
    source_title: str
    package: ActionPackage


class GameSession:
    """Application service for the local browser GUI.

    This object owns the live game state and exposes operations that a non-TUI
    caller can use directly. Rules still live in the engine, scenario, and
    orchestrator modules.
    """

    def __init__(
        self,
        *,
        scenario_selection: str | Path | None = DEFAULT_SCENARIO_ID,
        scenario_dir: str | Path | None = None,
        seed: int = 7,
        llm_client: LLMClient | None = None,
        output_dir: str | Path = "output/debug_sessions",
        save_dir: str | Path = "saves",
        load_save_path: str | Path | None = None,
        action_budget: int = NORMAL_ACTION_BUDGET,
        hard_action_limit: int = HARD_ACTION_BUDGET,
        max_turns: int = 10,
        debug_visible: bool = True,
    ) -> None:
        if action_budget < 0:
            raise ValueError("action_budget must be non-negative")
        if hard_action_limit < action_budget:
            raise ValueError("hard_action_limit must be >= action_budget")
        self.scenario = load_scenario(scenario_selection, scenario_dir=scenario_dir)
        self.world = self.scenario.create_initial_world(rng_seed=seed)
        self.player_id = self.scenario.player_entity_id
        self.save_dir = Path(save_dir)
        self.output_dir = Path(output_dir)
        self.action_budget = action_budget
        self.hard_action_limit = hard_action_limit
        self.max_turns = max_turns
        self.debug_visible = debug_visible
        self.llm_client = llm_client or _build_live_llm_client(
            campaign_seed=self.world.rng_seed,
            response_cache_dir=self.output_dir.parent / "llm_response_cache",
        )
        self.orchestrator = TurnOrchestrator(
            action_catalog=self.scenario.action_catalog,
            capabilities=self.scenario.capabilities,
            scenario_events=self.scenario.scenario_events,
            scenario_endings=self.scenario.scenario_endings,
            pressure_rules=self.scenario.pressure_rules,
            hidden_obligations=self.scenario.hidden_obligations,
            event_settings=self.scenario.event_settings,
            llm_client=self.llm_client,
            action_budget=action_budget,
            hard_action_limit=hard_action_limit,
            enable_chief_of_staff=True,
        )
        self.dialogue_engine = DialogueEngineAgent(
            action_catalog=self.scenario.action_catalog,
            capabilities=self.scenario.capabilities,
        )
        self.recorder = DebugSessionRecorder(
            world_state=self.world,
            player_entity_id=self.player_id,
            output_dir=self.output_dir,
        )
        self.plan_preview: PlayerPlanPreview | None = None
        self.plan_preview_rendered = ""
        self.agenda_items: list[AgendaSelection] = []
        self.latest_aftermath_report: TurnAftermathReport | None = None
        self.latest_result_rendered = ""
        self.latest_debug_text = ""
        self.latest_advisor_question = ""
        self.latest_advisor_response: AdvisorCouncilResponse | None = None
        if load_save_path is not None:
            self._load_save_path(Path(load_save_path))
        self.orchestrator.initialize_chief_plan(
            self.world,
            player_entity_id=self.player_id,
        )
        self.recorder.update_world_state(self.world)

    def close(self) -> None:
        close = getattr(self.llm_client, "close", None)
        if callable(close):
            close()

    def get_view(self) -> GameView:
        return build_game_view(self)

    def build_briefing(self) -> TurnBriefing:
        return build_turn_briefing(
            self.world,
            player_entity_id=self.player_id,
            action_catalog=self.scenario.action_catalog,
            capabilities=self.scenario.capabilities,
            action_budget=self.action_budget,
        )

    def ask_advisors(self, question: str) -> GameView:
        question = question.strip()
        if not question:
            raise ValueError("advisor question is empty")
        call_start = llm_call_count(self.llm_client)
        try:
            response = self.dialogue_engine.respond_to_player(
                self.world,
                player_entity_id=self.player_id,
                player_message=question,
                llm_client=self.llm_client,
                json_retries=1,
            )
        except LlamaCppJSONError as exc:
            raise ValueError(format_advisor_retry_error(exc)) from exc
        except Exception as exc:
            raise RuntimeError(format_runtime_error("Advisor dialogue", exc)) from exc
        self.latest_advisor_question = question
        self.latest_advisor_response = response
        self.recorder.append_dialogue(
            turn=self.world.turn_number,
            player_message=question,
            response=response,
            llm_calls=llm_call_records(self.llm_client, start_index=call_start),
        )
        self.recorder.save()
        return self.get_view()

    def preview_plan(self, text: str) -> GameView:
        text = text.strip()
        if not text:
            raise ValueError("plan text is empty")
        call_start = llm_call_count(self.llm_client)
        try:
            preview = build_player_plan_preview(
                self.world,
                player_entity_id=self.player_id,
                player_intent=text,
                gamemaster=self.orchestrator.gamemaster,
                action_catalog=self.scenario.action_catalog,
                capabilities=self.scenario.capabilities,
                scenario_events=self.scenario.scenario_events,
            )
        except Exception as exc:
            raise RuntimeError(format_runtime_error("Plan preview", exc)) from exc
        rendered = render_player_plan_preview(
            preview,
            action_catalog=self.scenario.action_catalog,
            capabilities=self.scenario.capabilities,
        )
        self.agenda_items.clear()
        self.plan_preview = preview
        self.plan_preview_rendered = rendered
        self.recorder.append_plan_preview(
            turn=self.world.turn_number,
            player_intent=text,
            preview=preview,
            rendered_text=rendered,
            llm_calls=llm_call_records(self.llm_client, start_index=call_start),
        )
        self.recorder.save()
        return self.get_view()

    def cancel_plan(self) -> GameView:
        self.plan_preview = None
        self.plan_preview_rendered = ""
        return self.get_view()

    def commit_plan(self) -> GameView:
        if self.plan_preview is None or not self.plan_preview.is_committable:
            raise ValueError("no committable plan preview is active")
        if not pending_plan_matches_world(
            self.plan_preview,
            self.world,
            self.player_id,
        ):
            self.plan_preview = None
            self.plan_preview_rendered = ""
            raise ValueError("the pending plan is stale; preview the plan again")
        self._resolve_turn(
            player_intent=self.plan_preview.player_intent,
            player_message="",
            precompiled_player_compilation=self.plan_preview.compilation,
        )
        return self.get_view()

    def submit_freeform_action(self, text: str) -> GameView:
        text = text.strip()
        if not text:
            raise ValueError("action text is empty")
        self._resolve_turn(player_intent=text, player_message="")
        return self.get_view()

    def select_action_card(self, card_id: str) -> GameView:
        if len(self.agenda_items) >= self.action_budget:
            raise ValueError(
                f"agenda already uses the {self.action_budget}-action turn bandwidth"
            )
        if any(item.card_id == card_id for item in self.agenda_items):
            raise ValueError("that action card is already on the agenda")
        package = self.package_for_card(card_id)
        validation = self.validate_package(package)
        if not validation.is_valid:
            raise ValueError("; ".join(validation.errors) or "action is not legal now")
        title, category, source_title = self.card_metadata(card_id, package)
        self.plan_preview = None
        self.plan_preview_rendered = ""
        self.agenda_items.append(
            AgendaSelection(
                agenda_item_id=str(uuid4()),
                card_id=card_id,
                title=title,
                category=category,
                source_title=source_title,
                package=package,
            )
        )
        return self.get_view()

    def remove_agenda_item(self, agenda_item_id: str) -> GameView:
        before = len(self.agenda_items)
        self.agenda_items = [
            item
            for item in self.agenda_items
            if item.agenda_item_id != agenda_item_id
        ]
        if len(self.agenda_items) == before:
            raise ValueError(f"agenda item not found: {agenda_item_id}")
        return self.get_view()

    def clear_agenda(self) -> GameView:
        self.agenda_items.clear()
        return self.get_view()

    def commit_agenda(self) -> GameView:
        if not self.agenda_items:
            raise ValueError("no actions queued")
        packages = [item.package.model_copy(deep=True) for item in self.agenda_items]
        errors: list[str] = []
        for package in packages:
            validation = self.validate_package(package)
            errors.extend(validation.errors)
        if errors:
            raise ValueError("; ".join(errors))
        compilation = GamemasterCompilation(
            action_packages=packages,
            action_package=packages[0] if packages else None,
            compiled_intents=[package.intent_summary for package in packages],
            action_budget=self.action_budget,
            hard_action_limit=self.hard_action_limit,
            notes=["Compiled from the GUI card agenda."],
        )
        self._resolve_turn(
            player_intent="; ".join(item.title for item in self.agenda_items),
            player_message="",
            precompiled_player_compilation=compilation,
        )
        return self.get_view()

    def end_turn(self) -> GameView:
        compilation = GamemasterCompilation(
            action_packages=[],
            action_budget=self.action_budget,
            hard_action_limit=self.hard_action_limit,
            notes=["Player held formal action this turn."],
        )
        self._resolve_turn(
            player_intent="hold no action this turn",
            player_message="",
            precompiled_player_compilation=compilation,
            allow_empty_player_action=True,
        )
        return self.get_view()

    def send_backchannel(self, target_query: str, message_text: str) -> GameView:
        target_query = target_query.strip()
        message_text = message_text.strip()
        if not target_query or not message_text:
            raise ValueError("backchannel target and message are required")
        target_id = resolve_backchannel_target(
            self.world,
            player_entity_id=self.player_id,
            target_query=target_query,
        )
        call_start = llm_call_count(self.llm_client)
        if target_id is not None:
            preparation = prepare_backchannel_message(
                self.world,
                player_entity_id=self.player_id,
                target_entity_id=target_id,
                message_text=message_text,
                action_catalog=self.scenario.action_catalog,
                capabilities=self.scenario.capabilities,
                llm_client=self.llm_client,
            )
            if not preparation.accepted:
                self.recorder.save()
                raise ValueError("; ".join(preparation.errors))
            if preparation.formal:
                preparation_calls = llm_call_records(
                    self.llm_client,
                    start_index=call_start,
                )
                if preparation_calls:
                    self.recorder.append_llm_task(
                        turn=self.world.turn_number,
                        label=preparation_calls[0].request.label,
                        llm_calls=preparation_calls,
                        rendered_text=(
                            f"[turn {self.world.turn_number} llm] "
                            f"{preparation_calls[0].request.label}"
                        ),
                    )
                assert preparation.compilation is not None
                self._resolve_turn(
                    player_intent=f"direct backchannel message to {target_id}",
                    player_message="",
                    precompiled_player_compilation=preparation.compilation,
                )
                return self.get_view()

        result = send_backchannel_message(
            self.world,
            player_entity_id=self.player_id,
            target_entity_id=target_id or "",
            target_query=target_query,
            message_text=message_text,
            action_catalog=self.scenario.action_catalog,
            capabilities=self.scenario.capabilities,
            llm_client=self.llm_client,
            info_channel=self.orchestrator.info_channel,
        )
        llm_calls = llm_call_records(self.llm_client, start_index=call_start)
        if llm_calls:
            self.recorder.append_llm_task(
                turn=self.world.turn_number,
                label=llm_calls[0].request.label,
                llm_calls=llm_calls,
                rendered_text=(
                    f"[turn {self.world.turn_number} llm] "
                    f"{llm_calls[0].request.label}"
                ),
            )
        if not result.accepted:
            self.recorder.save()
            raise ValueError("; ".join(result.errors))
        rendered = render_backchannel_direct_message_result(result)
        self.world = result.world_state
        self.latest_aftermath_report = None
        self.recorder.update_world_state(self.world, rendered_log_entry=rendered)
        self.latest_result_rendered = rendered
        self.latest_debug_text = rendered
        self.recorder.save()
        return self.get_view()

    def accept_ending(self, query: str = "latest") -> GameView:
        decision = accept_ending_offer(
            self.world,
            player_entity_id=self.player_id,
            offer_query=query or "latest",
        )
        if decision.errors:
            raise ValueError("; ".join(decision.errors))
        self.world = decision.world_state
        self._clear_turn_buffers()
        self.latest_result_rendered = decision.summary
        self.latest_debug_text = decision.summary
        self.recorder.update_world_state(self.world, rendered_log_entry=decision.summary)
        self.recorder.save()
        return self.get_view()

    def reject_ending(self, query: str = "latest") -> GameView:
        decision = reject_ending_offer(
            self.world,
            player_entity_id=self.player_id,
            offer_query=query or "latest",
        )
        if decision.errors:
            raise ValueError("; ".join(decision.errors))
        self.world = decision.world_state
        self._clear_turn_buffers()
        self.latest_result_rendered = decision.summary
        self.latest_debug_text = decision.summary
        self.recorder.update_world_state(self.world, rendered_log_entry=decision.summary)
        self.recorder.save()
        return self.get_view()

    def list_saves(self) -> list[SaveSummaryView]:
        if not self.save_dir.exists():
            return []
        summaries: list[SaveSummaryView] = []
        for path in sorted(self.save_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                record = load_playable_session(path)
            except Exception as exc:
                summaries.append(
                    SaveSummaryView(
                        save_id=path.stem,
                        display_name=path.stem,
                        scenario_id="",
                        compatible=False,
                        compatibility_error=f"Cannot parse save: {type(exc).__name__}: {exc}",
                    )
                )
                continue
            compatible = record.scenario_id == self.scenario.scenario_id
            display_name = str(record.metadata.get("display_name") or record.save_id)
            summaries.append(
                SaveSummaryView(
                    save_id=record.save_id,
                    display_name=display_name,
                    scenario_id=record.scenario_id,
                    scenario_title=(
                        self.scenario.metadata.title
                        if record.scenario_id == self.scenario.scenario_id
                        else record.scenario_id
                    ),
                    turn_number=record.world_state.turn_number,
                    time_label=record.world_state.time_label,
                    saved_at=record.saved_at,
                    player_entity_id=record.player_entity_id,
                    compatible=compatible,
                    compatibility_error=(
                        ""
                        if compatible
                        else (
                            "Save scenario does not match the active scenario. "
                            "Scenario switching is not part of this first GUI pass."
                        )
                    ),
                )
            )
        return summaries

    def save_game(self, name: str | None = None) -> GameView:
        self._write_save(name=name)
        return self.get_view()

    def load_save(self, save_id: str) -> GameView:
        save_id = save_id.strip()
        if not save_id:
            raise ValueError("save_id is required")
        stem = Path(save_id).name
        if stem.endswith(".json"):
            stem = stem[:-5]
        path = self.save_dir / f"{stem}.json"
        self._load_save_path(path)
        return self.get_view()

    def toggle_debug(self, enabled: bool | None = None) -> GameView:
        self.debug_visible = (not self.debug_visible) if enabled is None else bool(enabled)
        return self.get_view()

    def safe_package_for_card(self, card_id: str) -> ActionPackage | None:
        try:
            return self.package_for_card(card_id)
        except Exception:
            return None

    def package_for_card(self, card_id: str) -> ActionPackage:
        prefix, *parts = card_id.split("|")
        if prefix == ACTION_CARD_PREFIX and len(parts) == 1:
            return self._action_package_for_mechanical_id(parts[0])
        if prefix == EVENT_CHOICE_CARD_PREFIX and len(parts) == 2:
            package, errors = build_event_choice_action(
                self.world,
                player_entity_id=self.player_id,
                choice_query=parts[0],
                option_query=parts[1],
            )
            if package is None:
                raise ValueError("; ".join(errors) or f"event choice not found: {card_id}")
            return package
        raise ValueError(f"unknown action card: {card_id}")

    def card_metadata(
        self,
        card_id: str,
        package: ActionPackage,
    ) -> tuple[str, str, str]:
        prefix = card_id.split("|", 1)[0]
        if prefix == EVENT_CHOICE_CARD_PREFIX:
            for choice in self.world.pending_event_choices:
                if not choice.active_for(self.world.turn_number, self.player_id):
                    continue
                for option in choice.options:
                    if card_id == event_choice_card_id(choice.choice_id, option.option_id):
                        return option.label, "Event Choice", "Situation"
        definition, errors = ActionResolver(
            self.scenario.action_catalog,
            self.scenario.capabilities,
        ).resolve_package(package)
        title = definition.title if definition is not None and not errors else package.intent_summary
        category = definition.category.value.title() if definition is not None and not errors else "Action"
        source_title = _source_title_for_definition(definition, package)
        return title, category, source_title

    def validate_package(self, package: ActionPackage):
        return self.orchestrator.engine.validate_action(self.world, package)

    def _resolve_turn(
        self,
        *,
        player_intent: str,
        player_message: str,
        precompiled_player_compilation: GamemasterCompilation | None = None,
        allow_empty_player_action: bool = False,
    ) -> None:
        try:
            result = self.orchestrator.run_turn(
                self.world,
                player_entity_id=self.player_id,
                player_intent=player_intent,
                player_message=player_message,
                scenario_notes=self.scenario.metadata.designer_notes,
                precompiled_player_compilation=precompiled_player_compilation,
                allow_empty_player_action=allow_empty_player_action,
            )
        except (RecoverableAdvisorDialogueError, RecoverablePlayerActionError):
            raise
        except Exception as exc:
            raise RuntimeError(format_runtime_error("Turn", exc)) from exc
        self.world = result.world_state
        self.latest_aftermath_report = result.aftermath_report
        self.latest_result_rendered = render_aftermath_report(result.aftermath_report)
        self.latest_debug_text = result.debug_transcript.rendered_text
        self.recorder.append_turn(result.debug_transcript, self.world)
        self.recorder.save()
        self._clear_turn_buffers(keep_latest_result=True)

    def _clear_turn_buffers(self, *, keep_latest_result: bool = False) -> None:
        self.plan_preview = None
        self.plan_preview_rendered = ""
        self.agenda_items.clear()
        if not keep_latest_result:
            self.latest_aftermath_report = None

    def _write_save(self, *, name: str | None = None) -> Path:
        record = build_playable_save_record(
            world_state=self.world,
            player_entity_id=self.player_id,
            pending_plan=self.plan_preview if self.plan_preview and self.plan_preview.is_committable else None,
        )
        label = (name or "").strip()
        if label:
            record.metadata["display_name"] = label
        self.save_dir.mkdir(parents=True, exist_ok=True)
        path = self.save_dir / f"{record.save_id}.json"
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return path

    def _load_save_path(self, path: Path) -> None:
        record = load_playable_session(path)
        if record.scenario_id != self.scenario.scenario_id:
            raise ValueError(
                f"save scenario {record.scenario_id!r} does not match "
                f"{self.scenario.scenario_id!r}"
            )
        self.world = record.world_state
        if isinstance(self.llm_client, LlamaCppServerClient):
            self.llm_client.campaign_seed = self.world.rng_seed
        self.player_id = record.player_entity_id
        self.plan_preview = restore_pending_plan(record)
        self.plan_preview_rendered = ""
        self.agenda_items.clear()
        self.latest_aftermath_report = None
        self.latest_result_rendered = ""
        self.latest_debug_text = ""
        self.latest_advisor_question = ""
        self.latest_advisor_response = None
        self.recorder = DebugSessionRecorder(
            world_state=self.world,
            player_entity_id=self.player_id,
            output_dir=self.output_dir,
        )

    def _action_package_for_mechanical_id(self, mechanical_id: str) -> ActionPackage:
        definition = self._definition_for_mechanical_id(mechanical_id)
        targets = default_targets(self.world, self.player_id, definition)
        channel = default_channel(definition)
        package = ActionPackage(
            actor_id=self.player_id,
            action_id=definition.action_id,
            capability_id=definition.capability_id,
            target_ids=targets,
            channel=channel,
            intent_summary=definition.player_card_text
            or (definition.prompt_hints[0] if definition.prompt_hints else definition.title),
            public_rationale=definition.title,
            private_rationale=definition.player_card_text,
            submitted_turn=self.world.turn_number,
        )
        return package

    def _definition_for_mechanical_id(self, mechanical_id: str) -> ActionDefinition:
        player = self.world.require_entity(self.player_id)
        resolver = ActionResolver(self.scenario.action_catalog, self.scenario.capabilities)
        definitions = (
            resolver.resolved_capability_definitions()
            if self.scenario.capabilities
            else self.scenario.action_catalog
        )
        for definition in definitions:
            if definition.capability_id == mechanical_id or definition.action_id == mechanical_id:
                if not actor_allowed(player, definition):
                    raise ValueError(f"action is not available to {self.player_id}: {mechanical_id}")
                return definition
        briefing = self.build_briefing()
        available = ", ".join(action_card_id(card) for card in briefing.action_cards)
        raise ValueError(f"action card not found: {mechanical_id}. Available: {available}")


def _build_live_llm_client(
    *,
    campaign_seed: int,
    response_cache_dir: Path,
) -> LlamaCppServerClient:
    return LlamaCppServerClient(
        load_settings().llama_cpp,
        campaign_seed=campaign_seed,
        response_cache_dir=response_cache_dir,
    )


def _source_title_for_definition(
    definition: ActionDefinition | None,
    package: ActionPackage,
) -> str:
    mechanical_id = (package.capability_id or package.action_id).lower()
    if "direct_kremlin_message" in mechanical_id or "jupiter" in mechanical_id:
        return "Backchannels"
    if definition is None:
        return "Scenario"
    category = definition.category.value
    if "backchannel" in mechanical_id:
        return "Council: State"
    if category == "military":
        return "Council: Defense"
    if category == "intelligence":
        return "Council: Intelligence"
    if category in {"information", "domestic"} or "public" in mechanical_id:
        return "Council: Political"
    if category == "diplomatic":
        return "Council: State"
    return "Scenario"
