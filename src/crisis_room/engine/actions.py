from __future__ import annotations

from enum import Enum
from typing import TypeAlias, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

from crisis_room.state.signals import PayloadType, SignalChannel


class ActionCategory(str, Enum):
    DIPLOMATIC = "diplomatic"
    MILITARY = "military"
    INTELLIGENCE = "intelligence"
    ECONOMIC = "economic"
    DOMESTIC = "domestic"
    HUMANITARIAN = "humanitarian"
    INFORMATION = "information"
    GAMEMASTER = "gamemaster"


class CapabilityParameterKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    STRING_LIST = "string_list"


ActionParameterValue: TypeAlias = str | int | float | bool | list[str]
T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")


class CapabilityParameter(BaseModel):
    kind: CapabilityParameterKind
    required: bool = True
    allowed_values: list[str | int | float | bool] = Field(default_factory=list)


class ActionDefinition(BaseModel):
    """Generic action primitive or a resolved generic+capability action."""

    action_id: str
    title: str
    category: ActionCategory
    capability_id: str | None = None
    actor_types_allowed: list[str] = Field(default_factory=list)
    actor_ids_allowed: list[str] = Field(default_factory=list)
    targets_allowed: list[str] = Field(default_factory=list)
    target_ids_allowed: list[str] = Field(default_factory=list)
    channels_allowed: list[SignalChannel] = Field(default_factory=list)
    required_resources: dict[str, int] = Field(default_factory=dict)
    resource_costs: dict[str, int] = Field(default_factory=dict)
    actor_resource_effects: dict[str, int] = Field(default_factory=dict)
    target_resource_effects: dict[str, int] = Field(default_factory=dict)
    preparation_turns: int = Field(default=0, ge=0)
    execution_turns: int = Field(default=1, ge=0)
    min_targets: int = Field(default=0, ge=0)
    max_targets: int | None = Field(default=None, ge=0)
    preconditions: list[str] = Field(default_factory=list)
    truth_metric_effects: dict[str, float] = Field(default_factory=dict)
    public_metric_effects: dict[str, float] = Field(default_factory=dict)
    clock_effects: dict[str, int | float] = Field(default_factory=dict)
    relationship_effects: dict[str, float] = Field(default_factory=dict)
    escalation_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    deescalation_potential: float = Field(default=0.0, ge=0.0, le=1.0)
    information_outputs: list[PayloadType] = Field(default_factory=list)
    signal_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    signal_leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_distortion_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    public_timeline_title: str | None = None
    omniscient_timeline_title: str | None = None
    prompt_hints: list[str] = Field(default_factory=list)
    player_card_text: str = ""
    event_hooks: list[str] = Field(default_factory=list)
    message_budget: dict[str, int] = Field(default_factory=dict)
    parameter_schema: dict[str, CapabilityParameter] = Field(default_factory=dict)


class ScenarioCapability(BaseModel):
    """Scenario-specific affordance and mechanics bound to a generic action."""

    capability_id: str
    generic_action_id: str
    title: str
    category: ActionCategory | None = None
    actor_types_allowed: list[str] = Field(default_factory=list)
    actor_ids_allowed: list[str] = Field(default_factory=list)
    targets_allowed: list[str] = Field(default_factory=list)
    target_ids_allowed: list[str] = Field(default_factory=list)
    channels_allowed: list[SignalChannel] = Field(default_factory=list)
    required_resources: dict[str, int] = Field(default_factory=dict)
    resource_costs: dict[str, int] = Field(default_factory=dict)
    actor_resource_effects: dict[str, int] = Field(default_factory=dict)
    target_resource_effects: dict[str, int] = Field(default_factory=dict)
    preparation_turns: int = Field(default=0, ge=0)
    execution_turns: int = Field(default=1, ge=0)
    min_targets: int = Field(default=0, ge=0)
    max_targets: int | None = Field(default=None, ge=0)
    preconditions: list[str] = Field(default_factory=list)
    truth_metric_effects: dict[str, float] = Field(default_factory=dict)
    public_metric_effects: dict[str, float] = Field(default_factory=dict)
    clock_effects: dict[str, int | float] = Field(default_factory=dict)
    relationship_effects: dict[str, float] = Field(default_factory=dict)
    escalation_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    deescalation_potential: float = Field(default=0.0, ge=0.0, le=1.0)
    information_outputs: list[PayloadType] = Field(default_factory=list)
    signal_reliability: float = Field(default=1.0, ge=0.0, le=1.0)
    signal_leak_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_distortion_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    public_timeline_title: str | None = None
    omniscient_timeline_title: str | None = None
    prompt_hints: list[str] = Field(default_factory=list)
    player_card_text: str = ""
    event_hooks: list[str] = Field(default_factory=list)
    message_budget: dict[str, int] = Field(default_factory=dict)
    parameter_schema: dict[str, CapabilityParameter] = Field(default_factory=dict)


class ActionPackage(BaseModel):
    package_id: str = Field(default_factory=lambda: str(uuid4()))
    actor_id: str
    action_id: str
    capability_id: str | None = None
    target_ids: list[str] = Field(default_factory=list)
    channel: SignalChannel = SignalChannel.PRIVATE_DIPLOMATIC
    intent_summary: str
    public_rationale: str = ""
    private_rationale: str = ""
    commitment_level: float = Field(default=0.5, ge=0.0, le=1.0)
    submitted_turn: int | None = Field(default=None, ge=0)
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
    parameters: dict[str, ActionParameterValue] = Field(default_factory=dict)

    @property
    def mechanical_id(self) -> str:
        return self.capability_id or self.action_id


class ActionValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    action_definition_id: str | None = None
    capability_id: str | None = None


class ActionResolver:
    def __init__(
        self,
        action_catalog: list[ActionDefinition],
        capabilities: list[ScenarioCapability] | None = None,
    ) -> None:
        self.action_catalog = {definition.action_id: definition for definition in action_catalog}
        self.capabilities = {
            capability.capability_id: capability for capability in capabilities or []
        }

    def resolve_package(
        self,
        package: ActionPackage,
    ) -> tuple[ActionDefinition | None, list[str]]:
        generic = self.action_catalog.get(package.action_id)
        if generic is None:
            return None, [f"unknown action: {package.action_id}"]
        if not self.capabilities:
            return generic, []
        if not package.capability_id:
            return None, [f"capability_id is required for {package.action_id}"]
        capability = self.capabilities.get(package.capability_id)
        if capability is None:
            return None, [f"unknown capability: {package.capability_id}"]
        if capability.generic_action_id != package.action_id:
            return (
                None,
                [
                    f"capability {capability.capability_id} requires action "
                    f"{capability.generic_action_id}, got {package.action_id}"
                ],
            )
        parameter_errors = validate_capability_parameters(capability, package.parameters)
        if parameter_errors:
            return None, parameter_errors
        return resolved_action_definition(generic, capability), []

    def resolved_capability_definitions(self) -> list[ActionDefinition]:
        definitions: list[ActionDefinition] = []
        for capability in self.capabilities.values():
            generic = self.action_catalog.get(capability.generic_action_id)
            if generic is None:
                continue
            definitions.append(resolved_action_definition(generic, capability))
        return definitions


def resolved_action_definition(
    generic: ActionDefinition,
    capability: ScenarioCapability,
) -> ActionDefinition:
    return generic.model_copy(
        deep=True,
        update={
            "capability_id": capability.capability_id,
            "title": capability.title,
            "category": capability.category or generic.category,
            "actor_types_allowed": _inherit_list(
                capability.actor_types_allowed,
                generic.actor_types_allowed,
            ),
            "actor_ids_allowed": capability.actor_ids_allowed,
            "targets_allowed": _inherit_list(
                capability.targets_allowed,
                generic.targets_allowed,
            ),
            "target_ids_allowed": capability.target_ids_allowed,
            "channels_allowed": _inherit_list(
                capability.channels_allowed,
                generic.channels_allowed,
            ),
            "required_resources": _merge_dicts(
                generic.required_resources,
                capability.required_resources,
            ),
            "resource_costs": _merge_dicts(
                generic.resource_costs,
                capability.resource_costs,
            ),
            "actor_resource_effects": _merge_dicts(
                generic.actor_resource_effects,
                capability.actor_resource_effects,
            ),
            "target_resource_effects": _merge_dicts(
                generic.target_resource_effects,
                capability.target_resource_effects,
            ),
            "preparation_turns": capability.preparation_turns,
            "execution_turns": capability.execution_turns,
            "min_targets": capability.min_targets,
            "max_targets": capability.max_targets,
            "preconditions": [*generic.preconditions, *capability.preconditions],
            "truth_metric_effects": _merge_dicts(
                generic.truth_metric_effects,
                capability.truth_metric_effects,
            ),
            "public_metric_effects": _merge_dicts(
                generic.public_metric_effects,
                capability.public_metric_effects,
            ),
            "clock_effects": _merge_dicts(
                generic.clock_effects,
                capability.clock_effects,
            ),
            "relationship_effects": _merge_dicts(
                generic.relationship_effects,
                capability.relationship_effects,
            ),
            "escalation_risk": max(generic.escalation_risk, capability.escalation_risk),
            "deescalation_potential": max(
                generic.deescalation_potential,
                capability.deescalation_potential,
            ),
            "information_outputs": _inherit_list(
                capability.information_outputs,
                generic.information_outputs,
            ),
            "signal_reliability": capability.signal_reliability,
            "signal_leak_risk": capability.signal_leak_risk,
            "signal_distortion_risk": capability.signal_distortion_risk,
            "public_timeline_title": (
                capability.public_timeline_title or generic.public_timeline_title
            ),
            "omniscient_timeline_title": (
                capability.omniscient_timeline_title
                or generic.omniscient_timeline_title
            ),
            "prompt_hints": [*generic.prompt_hints, *capability.prompt_hints],
            "player_card_text": capability.player_card_text or generic.player_card_text,
            "event_hooks": [*generic.event_hooks, *capability.event_hooks],
            "message_budget": _merge_dicts(
                generic.message_budget,
                capability.message_budget,
            ),
            "parameter_schema": capability.parameter_schema,
        },
    )


def validate_capability_parameters(
    capability: ScenarioCapability,
    parameters: dict[str, ActionParameterValue],
) -> list[str]:
    schema = capability.parameter_schema
    allowed = set(schema)
    supplied = set(parameters)
    errors: list[str] = []
    extra = sorted(supplied - allowed)
    if extra:
        errors.append(
            f"{capability.capability_id} parameters include unsupported keys: "
            f"{', '.join(extra)}"
        )
    missing = sorted(
        name
        for name, parameter in schema.items()
        if parameter.required and name not in parameters
    )
    if missing:
        errors.append(
            f"{capability.capability_id} parameters missing required keys: "
            f"{', '.join(missing)}"
        )
    for name, value in parameters.items():
        parameter = schema.get(name)
        if parameter is None:
            continue
        if not _parameter_kind_matches(value, parameter.kind):
            errors.append(
                f"{capability.capability_id}.{name} must be {parameter.kind.value}"
            )
            continue
        if parameter.allowed_values and value not in parameter.allowed_values:
            allowed_values = ", ".join(str(item) for item in parameter.allowed_values)
            errors.append(
                f"{capability.capability_id}.{name} must be one of: {allowed_values}"
            )
    return errors


def _parameter_kind_matches(
    value: ActionParameterValue,
    kind: CapabilityParameterKind,
) -> bool:
    if kind == CapabilityParameterKind.STRING:
        return isinstance(value, str)
    if kind == CapabilityParameterKind.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == CapabilityParameterKind.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == CapabilityParameterKind.BOOLEAN:
        return isinstance(value, bool)
    if kind == CapabilityParameterKind.STRING_LIST:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def _inherit_list(override: list[T], fallback: list[T]) -> list[T]:
    return list(override) if override else list(fallback)


def _merge_dicts(first: dict[K, V], second: dict[K, V]) -> dict[K, V]:
    merged = dict(first)
    merged.update(second)
    return merged
