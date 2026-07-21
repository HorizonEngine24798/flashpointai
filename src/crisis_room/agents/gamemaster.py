from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.config.gameplay import (
    GAMEMASTER_MAX_TOKENS,
    HARD_ACTION_BUDGET,
    NORMAL_ACTION_BUDGET,
)
from crisis_room.engine.action_matching import default_targets
from crisis_room.engine.actions import (
    ActionDefinition,
    ActionPackage,
    ScenarioCapability,
)
from crisis_room.engine.adjudication import DeterministicEngineV2
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.prompts import gamemaster_system, gamemaster_task
from crisis_room.llm.task_contracts import (
    IntentCompilationCandidate,
    MultiIntentCompilation,
)
from crisis_room.state.signals import SignalChannel
from crisis_room.state.world import WorldStateV2


class GamemasterCompilation(BaseModel):
    action_packages: list[ActionPackage] = Field(default_factory=list)
    action_package: ActionPackage | None = None
    compiled_intents: list[str] = Field(default_factory=list)
    rejected_intents: list[str] = Field(default_factory=list)
    unprocessed_intents: list[str] = Field(default_factory=list)
    action_budget: int = NORMAL_ACTION_BUDGET
    hard_action_limit: int = HARD_ACTION_BUDGET
    rejected: bool = False
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _sync_primary_action_package(cls, raw: Any) -> Any:
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


class CatalogGamemasterCompiler:
    """LLM intent compiler constrained by the scenario action catalog."""

    def __init__(
        self,
        action_catalog: list[ActionDefinition],
        llm_client: LLMClient,
        capabilities: list[ScenarioCapability] | None = None,
        action_budget: int = NORMAL_ACTION_BUDGET,
        hard_action_limit: int = HARD_ACTION_BUDGET,
    ) -> None:
        if action_budget < 0:
            raise ValueError("action_budget must be non-negative")
        if hard_action_limit < action_budget:
            raise ValueError("hard_action_limit must be >= action_budget")
        self.action_catalog = action_catalog
        self.capabilities = capabilities or []
        self.llm_client = llm_client
        self.action_budget = action_budget
        self.hard_action_limit = hard_action_limit
        self._catalog_by_id = {
            definition.action_id: definition for definition in action_catalog
        }
        self._capabilities_by_id = {
            capability.capability_id: capability for capability in self.capabilities
        }
        self._engine = DeterministicEngineV2(action_catalog, self.capabilities)

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
            capabilities=self.capabilities,
            player_message=text,
        )
        request = build_task_request(
            label=f"gamemaster.{actor_id}.intent_compilation",
            system_prompt=gamemaster_system(self.hard_action_limit),
            visible_context=visible_context,
            task_instruction=gamemaster_task(self.action_budget, self.hard_action_limit),
            response_schema_name="MultiIntentCompilation",
            metadata={
                "agent": "gamemaster",
                "actor_id": actor_id,
                "turn_number": world_state.turn_number,
            },
            max_tokens=GAMEMASTER_MAX_TOKENS,
        )
        compiled = self.llm_client.complete_json(request, MultiIntentCompilation)
        if compiled.accepted and not compiled.candidates:
            return GamemasterCompilation(
                rejected=True,
                action_budget=self.action_budget,
                hard_action_limit=self.hard_action_limit,
                errors=["intent compiler accepted without candidates"],
                notes=compiled.notes,
            )
        if not compiled.accepted and not compiled.candidates:
            return GamemasterCompilation(
                rejected=bool(compiled.errors),
                action_budget=self.action_budget,
                hard_action_limit=self.hard_action_limit,
                rejected_intents=list(compiled.rejected_intents),
                errors=compiled.errors,
                notes=compiled.notes,
            )

        action_packages: list[ActionPackage] = []
        compiled_intents: list[str] = []
        rejected_intents: list[str] = list(compiled.rejected_intents)
        unprocessed_intents: list[str] = []
        errors: list[str] = list(compiled.errors)
        notes: list[str] = list(compiled.notes)
        notes.extend(f"rejected intent: {intent}" for intent in compiled.rejected_intents)

        bounded_candidates = compiled.candidates[: self.hard_action_limit]
        candidate_budget = bounded_candidates[: self.action_budget]
        extra_candidates = bounded_candidates[self.action_budget :]
        unprocessed_intents.extend(
            _candidate_intent_label(candidate)
            for candidate in extra_candidates
        )
        overflow_count = len(compiled.candidates) - len(bounded_candidates)
        if overflow_count > 0:
            unprocessed_intents.append(
                f"{overflow_count} additional candidate action(s) above the hard maximum"
            )
            notes.append(
                f"intent compiler returned {len(compiled.candidates)} candidates; "
                f"only the first {self.hard_action_limit} were inspected"
            )
        notes.extend(
            f"unprocessed intent: {intent} (normal action budget is {self.action_budget})"
            for intent in unprocessed_intents
        )

        for index, candidate in enumerate(candidate_budget, start=1):
            if not candidate.accepted:
                rejected_intents.append(_candidate_rejection(candidate))
            package, candidate_errors, candidate_notes = self._compile_candidate(
                world_state,
                actor_id,
                candidate,
                index=index,
                source_text=text,
            )
            notes.extend(candidate_notes)
            if candidate_errors:
                errors.extend(candidate_errors)
                rejected_intents.append(
                    f"{_candidate_intent_label(candidate)}: {'; '.join(candidate_errors)}"
                )
                continue
            if package is not None:
                if (
                    package.capability_id == _UNORTHODOX_CAPABILITY_ID
                    and any(
                        existing.capability_id == _UNORTHODOX_CAPABILITY_ID
                        for existing in action_packages
                    )
                ):
                    # ponytail: one generic gambit per turn; use a compound capability
                    # if a scenario needs several simultaneous unorthodox premises.
                    label = _candidate_intent_label(candidate)
                    unprocessed_intents.append(
                        f"{label} (only one {_UNORTHODOX_CAPABILITY_ID} is allowed per turn)"
                    )
                    notes.append(
                        f"intent {index}: skipped duplicate {_UNORTHODOX_CAPABILITY_ID}; "
                        "one generic gambit is the per-turn limit"
                    )
                    continue
                action_packages.append(package)
                compiled_intents.append(package.intent_summary)

        rejected = not action_packages and bool(errors)
        return GamemasterCompilation(
            action_packages=action_packages,
            action_package=action_packages[0] if action_packages else None,
            compiled_intents=_dedupe(compiled_intents),
            rejected_intents=_dedupe(rejected_intents),
            unprocessed_intents=_dedupe(unprocessed_intents),
            action_budget=self.action_budget,
            hard_action_limit=self.hard_action_limit,
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
        source_text: str,
    ) -> tuple[ActionPackage | None, list[str], list[str]]:
        prefix = f"intent {index}"
        notes = list(candidate.notes)
        if not candidate.accepted:
            return None, [], [f"{prefix} rejected by compiler: {_candidate_rejection(candidate)}"]
        fallback = self._unorthodox_fallback_candidate(candidate, source_text)
        if fallback is not None:
            candidate = fallback
            notes.append(f"{prefix}: routed absurd non-catalog intent through {_UNORTHODOX_CAPABILITY_ID}")
        if not candidate.action_id:
            return None, [f"{prefix}: intent compiler accepted without action_id"], notes
        if candidate.action_id not in self._catalog_by_id:
            return (
                None,
                [f"{prefix}: intent compiler returned non-catalog action: {candidate.action_id}"],
                notes,
            )
        if self.capabilities and not candidate.capability_id:
            return None, [f"{prefix}: intent compiler accepted without capability_id"], notes
        if candidate.capability_id and candidate.capability_id not in self._capabilities_by_id:
            return (
                None,
                [
                    f"{prefix}: intent compiler returned non-catalog capability: "
                    f"{candidate.capability_id}"
                ],
                notes,
            )
        if not candidate.intent_summary.strip():
            return None, [f"{prefix}: intent compiler returned empty intent_summary"], notes
        semantic_errors = _semantic_substitution_errors(
            candidate,
            source_text=source_text,
            prefix=prefix,
        )
        if semantic_errors:
            return None, semantic_errors, notes

        target_ids = list(candidate.target_ids)
        if candidate.capability_id and not target_ids:
            definition = next(
                (
                    definition
                    for definition in self._engine.resolver.resolved_capability_definitions()
                    if definition.action_id == candidate.action_id
                    and definition.capability_id == candidate.capability_id
                ),
                None,
            )
            if definition is not None:
                target_ids = default_targets(world_state, actor_id, definition)
                if target_ids:
                    notes.append(
                        f"{prefix}: Filled default target(s): {', '.join(target_ids)}"
                    )

        parameters = dict(candidate.parameters)
        if candidate.capability_id == _UNORTHODOX_CAPABILITY_ID and "premise" not in parameters:
            parameters["premise"] = candidate.source_span or source_text or candidate.intent_summary

        package = ActionPackage(
            actor_id=actor_id,
            action_id=candidate.action_id,
            capability_id=candidate.capability_id,
            target_ids=target_ids,
            channel=candidate.channel,
            intent_summary=candidate.intent_summary,
            public_rationale=candidate.public_rationale,
            private_rationale=candidate.private_rationale,
            commitment_level=candidate.commitment_level,
            submitted_turn=world_state.turn_number,
            metadata={
                "created_by": "CatalogGamemasterCompiler",
                "intent_index": index,
                "source_span": candidate.source_span,
            },
            parameters=parameters,
        )
        validation = self._engine.validate_action(world_state, package)
        if not validation.is_valid:
            return package, [f"{prefix}: {error}" for error in validation.errors], notes
        notes.extend(f"{prefix} warning: {warning}" for warning in validation.warnings)
        return package, [], notes

    def _unorthodox_fallback_candidate(
        self,
        candidate: IntentCompilationCandidate,
        source_text: str,
    ) -> IntentCompilationCandidate | None:
        capability = self._capabilities_by_id.get(_UNORTHODOX_CAPABILITY_ID)
        if capability is None:
            return None
        action_ok = candidate.action_id in self._catalog_by_id
        capability_ok = candidate.capability_id in self._capabilities_by_id
        if action_ok and capability_ok:
            return None
        source = candidate.source_span or source_text or candidate.intent_summary
        if candidate.capability_id != _UNORTHODOX_CAPABILITY_ID and not _contains_any(
            source.lower(),
            _ABSURD_PREMISE_MARKERS,
        ):
            return None
        channel = (
            candidate.channel
            if candidate.channel in capability.channels_allowed
            else capability.channels_allowed[0]
            if capability.channels_allowed
            else SignalChannel.PRIVATE_DIPLOMATIC
        )
        return candidate.model_copy(
            update={
                "action_id": capability.generic_action_id,
                "capability_id": capability.capability_id,
                "channel": channel,
                "intent_summary": candidate.intent_summary
                or f"Preserve unorthodox premise: {source[:160]}",
                "parameters": {**candidate.parameters, "premise": source},
                "source_span": candidate.source_span or source[:160],
            }
        )


def _candidate_rejection(candidate: IntentCompilationCandidate) -> str:
    if candidate.errors:
        return "; ".join(candidate.errors)
    if candidate.intent_summary:
        return candidate.intent_summary
    if candidate.source_span:
        return candidate.source_span
    return "no deterministic action fits"


def _candidate_intent_label(candidate: IntentCompilationCandidate) -> str:
    if candidate.intent_summary:
        return candidate.intent_summary
    if candidate.source_span:
        return candidate.source_span
    if candidate.capability_id:
        return candidate.capability_id
    if candidate.action_id:
        return candidate.action_id
    return "unlabeled intent"


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


_UNORTHODOX_CAPABILITY_ID = "cuba_unorthodox_gambit"

_ABSURD_PREMISE_MARKERS = (
    "alien",
    "alaska",
    "mars",
    "moon landing",
    "cyber",
    "drone",
    "teleport",
    "time machine",
    "colony ship",
    "nationalize",
    "arrest khrushchev",
    "join nato",
)

_SEMANTICALLY_SENSITIVE_CAPABILITIES = {
    "cuba_secret_jupiter_trade": (
        "jupiter",
        "turkey",
        "missile trade",
        "missile swap",
    ),
    "cuba_offer_non_invasion_pledge": (
        "non-invasion",
        "non invasion",
        "pledge",
        "guarantee",
    ),
    "cuba_open_kremlin_channel": (
        "backchannel",
        "kremlin",
        "dobrynin",
        "private channel",
    ),
    "cuba_monitor_public_mood": (
        "public mood",
        "monitor",
        "press",
        "media",
        "poll",
    ),
    "cuba_rally_institutional_allies": (
        "allies",
        "allied",
        "nato allies",
        "congress",
        "cabinet",
    ),
}


def _semantic_substitution_errors(
    candidate: IntentCompilationCandidate,
    *,
    source_text: str,
    prefix: str,
) -> list[str]:
    capability_id = candidate.capability_id or ""
    if capability_id == _UNORTHODOX_CAPABILITY_ID:
        return []
    source = (candidate.source_span or source_text or candidate.intent_summary).lower()
    if not _contains_any(source, _ABSURD_PREMISE_MARKERS):
        return []
    expected = _SEMANTICALLY_SENSITIVE_CAPABILITIES.get(capability_id)
    if expected is None or _contains_any(source, expected):
        return []
    return [
        (
            f"{prefix}: source premise is absurd or ahistorical; use "
            f"{_UNORTHODOX_CAPABILITY_ID} or reject it instead of {capability_id}"
        )
    ]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
