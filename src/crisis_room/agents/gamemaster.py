from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.engine.actions import ActionDefinition, ActionPackage
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.task_contracts import (
    IntentCompilationCandidate,
    MultiIntentCompilation,
)
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


class GamemasterCompilation(BaseModel):
    action_packages: list[ActionPackage] = Field(default_factory=list)
    action_package: ActionPackage | None = None
    rejected: bool = False
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _mirror_legacy_fields(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        values = dict(raw)
        if "action_packages" not in values:
            action_package = values.get("action_package")
            values["action_packages"] = [action_package] if action_package is not None else []
        if values.get("action_package") is None and values.get("action_packages"):
            values["action_package"] = values["action_packages"][0]
        return values


class Gamemaster(Protocol):
    def compile_player_intent(
        self,
        world_state: WorldStateV2,
        actor_id: str,
        intent_text: str,
    ) -> GamemasterCompilation:
        """Convert player freeform intent into a deterministic action package."""


class SimpleGamemaster:
    """Minimal compiler for the Phase 1 fake turn path."""

    def compile_player_intent(
        self,
        world_state: WorldStateV2,
        actor_id: str,
        intent_text: str,
    ) -> GamemasterCompilation:
        text = intent_text.strip()
        if not text:
            return GamemasterCompilation(
                rejected=True,
                errors=["formal action text is empty"],
            )
        if actor_id not in world_state.actors:
            return GamemasterCompilation(
                rejected=True,
                errors=[f"unknown actor: {actor_id}"],
            )

        channel = _guess_channel(text)
        target_ids = [entity_id for entity_id in world_state.actors if entity_id != actor_id]
        package = ActionPackage(
            actor_id=actor_id,
            action_id="player_freeform_intent",
            target_ids=target_ids,
            channel=channel,
            intent_summary=text,
            private_rationale="Compiled from player ACTION input by SimpleGamemaster.",
            submitted_turn=world_state.turn_number,
        )
        return GamemasterCompilation(
            action_packages=[package],
            action_package=package,
            notes=[
                "Compiled freeform player intent into the placeholder action primitive.",
                f"Guessed channel: {channel.value}",
            ],
        )


class CatalogGamemasterCompiler:
    """LLM intent compiler constrained by the scenario action catalog."""

    def __init__(
        self,
        action_catalog: list[ActionDefinition],
        llm_client: LLMClient,
    ) -> None:
        self.action_catalog = action_catalog
        self.llm_client = llm_client
        self._catalog_by_id = {
            definition.action_id: definition for definition in action_catalog
        }
        self._engine = DeterministicEngineV2(action_catalog)

    def compile_player_intent(
        self,
        world_state: WorldStateV2,
        actor_id: str,
        intent_text: str,
    ) -> GamemasterCompilation:
        text = intent_text.strip()
        if not text:
            return GamemasterCompilation(
                rejected=True,
                errors=["formal action text is empty"],
            )
        if actor_id not in world_state.actors:
            return GamemasterCompilation(
                rejected=True,
                errors=[f"unknown actor: {actor_id}"],
            )

        actor_state = world_state.actors[actor_id]
        visible_context = build_visible_context(
            actor_state,
            world_state,
            action_catalog=self.action_catalog,
            player_message=text,
        )
        request = build_task_request(
            label=f"gamemaster.{actor_id}.intent_compilation",
            system_prompt=(
                "You are the gamemaster intent compiler. Translate player ACTION "
                "text into zero to three scenario catalog action package candidates. "
                "You do not resolve effects."
            ),
            visible_context=visible_context,
            task_instruction=(
                "Compile the player ACTION text into a MultiIntentCompilation. Use "
                "only action ids, target ids, and channels present in the visible "
                "context. Split clearly separate intents when the player asks for "
                "multiple concrete actions. Do not invent more than three actions. "
                "Prefer fewer actions if the text describes one integrated action. "
                "Reject individual intents that cannot be represented legally, "
                "require unavailable targets, or ask for guaranteed effects outside "
                "the deterministic engine."
            ),
            response_schema_name="MultiIntentCompilation",
            metadata={
                "agent": "gamemaster",
                "actor_id": actor_id,
                "turn_number": world_state.turn_number,
            },
            max_tokens=1800,
        )
        compiled = self.llm_client.complete_json(request, MultiIntentCompilation)
        if compiled.accepted and not compiled.candidates:
            return GamemasterCompilation(
                rejected=True,
                errors=["intent compiler accepted without candidates"],
                notes=compiled.notes,
            )
        if not compiled.accepted and not compiled.candidates:
            return GamemasterCompilation(
                rejected=bool(compiled.errors),
                errors=compiled.errors,
                notes=compiled.notes,
            )

        action_packages: list[ActionPackage] = []
        errors: list[str] = list(compiled.errors)
        notes: list[str] = list(compiled.notes)
        notes.extend(f"rejected intent: {intent}" for intent in compiled.rejected_intents)

        for index, candidate in enumerate(compiled.candidates[:3], start=1):
            package, candidate_errors, candidate_notes = self._compile_candidate(
                world_state,
                actor_id,
                candidate,
                index=index,
            )
            notes.extend(candidate_notes)
            if candidate_errors:
                errors.extend(candidate_errors)
                continue
            if package is not None:
                action_packages.append(package)

        rejected = not action_packages and bool(errors)
        return GamemasterCompilation(
            action_packages=action_packages,
            action_package=action_packages[0] if action_packages else None,
            rejected=rejected,
            errors=_dedupe(errors),
            notes=_dedupe(notes),
        )

    def _compile_candidate(
        self,
        world_state: WorldStateV2,
        actor_id: str,
        candidate: IntentCompilationCandidate,
        *,
        index: int,
    ) -> tuple[ActionPackage | None, list[str], list[str]]:
        prefix = f"intent {index}"
        notes = list(candidate.notes)
        if not candidate.accepted:
            return None, [], [f"{prefix} rejected by compiler: {_candidate_rejection(candidate)}"]
        if not candidate.action_id:
            return None, [f"{prefix}: intent compiler accepted without action_id"], notes
        if candidate.action_id not in self._catalog_by_id:
            return (
                None,
                [f"{prefix}: intent compiler returned non-catalog action: {candidate.action_id}"],
                notes,
            )
        if not candidate.intent_summary.strip():
            return None, [f"{prefix}: intent compiler returned empty intent_summary"], notes

        package = ActionPackage(
            actor_id=actor_id,
            action_id=candidate.action_id,
            target_ids=candidate.target_ids,
            channel=candidate.channel,
            intent_summary=candidate.intent_summary,
            public_rationale=candidate.public_rationale,
            private_rationale=candidate.private_rationale,
            requested_timing=candidate.requested_timing,
            commitment_level=candidate.commitment_level,
            risk_acceptance=candidate.risk_acceptance,
            fallback_condition=candidate.fallback_condition,
            submitted_turn=world_state.turn_number,
            metadata={
                "created_by": "CatalogGamemasterCompiler",
                "intent_index": index,
                "source_span": candidate.source_span,
            },
        )
        validation = self._engine.validate_action(world_state, package)
        if not validation.is_valid:
            return package, [f"{prefix}: {error}" for error in validation.errors], notes
        notes.extend(f"{prefix} warning: {warning}" for warning in validation.warnings)
        return package, [], notes


def _guess_channel(text: str) -> SignalChannel:
    lowered = text.lower()
    if "public" in lowered or "announce" in lowered or "statement" in lowered:
        return SignalChannel.PUBLIC
    if "backchannel" in lowered:
        return SignalChannel.BACKCHANNEL
    if "intel" in lowered or "intelligence" in lowered:
        return SignalChannel.INTEL
    if "military" in lowered or "readiness" in lowered or "quarantine" in lowered:
        return SignalChannel.MILITARY
    return SignalChannel.PRIVATE_DIPLOMATIC


def _candidate_rejection(candidate: IntentCompilationCandidate) -> str:
    if candidate.errors:
        return "; ".join(candidate.errors)
    if candidate.intent_summary:
        return candidate.intent_summary
    if candidate.source_span:
        return candidate.source_span
    return "no deterministic action fits"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
