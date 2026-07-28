from __future__ import annotations

from pydantic import BaseModel, Field

from crisis_room.agents.context import build_task_request, build_visible_context
from crisis_room.engine.action_matching import actor_allowed, default_channel, default_targets
from crisis_room.engine.actions import ActionDefinition, ActionPackage, ActionResolver, ScenarioCapability
from crisis_room.engine.adjudication import DeterministicEngineV2, DeterministicTurnResult
from crisis_room.llm.contracts import LLMClient
from crisis_room.llm.prompts import CHIEF_SYSTEM, CHIEF_TASK
from crisis_room.llm.task_contracts import ChiefPlanResponse
from crisis_room.state.advisors import ChiefAward, ChiefPlanState
from crisis_room.state.world import WorldStateV2


CHIEF_ASSESSMENTS = {"initial", "continue", "revise", "completed"}


class ChiefReviewResult(BaseModel):
    update_lines: list[str] = Field(default_factory=list)
    error: str = ""


def review_chief_plan(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
    llm_client: LLMClient,
    action_budget: int,
    review_turn: int,
    deterministic_result: DeterministicTurnResult | None = None,
) -> ChiefReviewResult:
    player = world_state.require_entity(player_entity_id)
    previous = world_state.chief_plan
    legal_capability_ids = _legal_capability_ids(
        world_state,
        player_entity_id=player_entity_id,
        action_catalog=action_catalog,
        capabilities=capabilities,
    )
    allowed_rewards = sorted(player.resources)
    extra = {
        "chief_profile": _chief_profile(world_state, player_entity_id),
        "review_turn": review_turn,
        "action_budget": action_budget,
        "legal_capability_ids": legal_capability_ids,
        "allowed_reward_resources": allowed_rewards,
        "reward_rules": (
            "At most one point of one existing resource, only after completing a prior plan."
        ),
        "previous_plan": previous.model_dump(mode="json") if previous else None,
        "last_player_actions": _player_action_context(
            deterministic_result,
            player_entity_id=player_entity_id,
        ),
    }
    request = build_task_request(
        label=f"chief.{player_entity_id}.plan_review",
        system_prompt=CHIEF_SYSTEM,
        visible_context=build_visible_context(
            player,
            world_state,
            action_catalog=action_catalog,
            capabilities=capabilities,
            extra=extra,
        ),
        task_instruction=CHIEF_TASK,
        response_schema_name="ChiefPlanResponse",
        metadata={
            "agent": "chief_of_staff",
            "player_entity_id": player_entity_id,
            "turn_number": review_turn,
        },
    )
    try:
        response = llm_client.complete_json(request, ChiefPlanResponse)
    except Exception as exc:
        response = _fallback_response(previous, legal_capability_ids, action_budget)
        error = f"Chief plan review fell back after {type(exc).__name__}."
    else:
        error = ""

    assessment = response.assessment.strip().lower()
    if assessment not in CHIEF_ASSESSMENTS:
        assessment = "revise" if previous else "initial"
    if previous is None:
        assessment = "initial"
    elif assessment == "initial":
        assessment = "revise"

    recommendations = _validated_recommendations(
        response.recommended_capability_ids,
        legal_capability_ids=legal_capability_ids,
        action_budget=action_budget,
    )
    if not recommendations:
        recommendations = legal_capability_ids[: max(action_budget, 0)]

    assessment_summary = response.assessment_summary
    completed_ids = list(previous.completed_plan_ids) if previous else []
    awards = list(previous.awards) if previous else []
    plan_id = previous.plan_id if previous else _plan_id(review_turn, 1)
    created_turn = previous.created_turn if previous else review_turn
    review_count = (previous.review_count + 1) if previous else 1
    objectives = [item.strip() for item in response.objectives if item.strip()]
    if not objectives:
        objectives = (
            list(previous.objectives)
            if previous and previous.objectives
            else ["Preserve presidential options while improving the crisis position."]
        )
    rationale = response.rationale

    completed_prior = (
        previous is not None
        and assessment == "completed"
        and review_turn > previous.created_turn
        and previous.plan_id not in previous.completed_plan_ids
        and bool(_successful_player_actions(deterministic_result, player_entity_id))
    )
    if assessment == "completed" and not completed_prior:
        assessment = "continue"
        assessment_summary = (
            "The plan remains active; no completed player action yet supports an award."
        )
    lines = [assessment_summary]
    if completed_prior:
        completed_ids.append(previous.plan_id)
        award = _apply_reward(
            player.resources,
            previous_plan_id=previous.plan_id,
            review_turn=review_turn,
            resource=response.reward_resource,
            reason=response.reward_reason,
        )
        if award is not None:
            awards.append(award)
            lines.append(
                f"Awarded {_label(award.resource)} {award.before} → {award.after} (+1): "
                f"{award.reason or 'objective completed.'}"
            )
        plan_id = _plan_id(review_turn, review_count)
        created_turn = review_turn
    elif assessment == "revise":
        plan_id = _plan_id(review_turn, review_count)
        created_turn = review_turn
    elif previous is not None:
        objectives = list(previous.objectives)

    world_state.chief_plan = ChiefPlanState(
        plan_id=plan_id,
        created_turn=created_turn,
        last_reviewed_turn=review_turn,
        review_count=review_count,
        objectives=objectives,
        rationale=rationale,
        recommended_capability_ids=recommendations,
        latest_assessment=assessment_summary,
        completed_plan_ids=completed_ids,
        awards=awards,
    )
    _remember_recommendation(world_state, player_entity_id, objectives)
    return ChiefReviewResult(update_lines=lines, error=error)


def _legal_capability_ids(
    world_state: WorldStateV2,
    *,
    player_entity_id: str,
    action_catalog: list[ActionDefinition],
    capabilities: list[ScenarioCapability],
) -> list[str]:
    player = world_state.require_entity(player_entity_id)
    resolver = ActionResolver(action_catalog, capabilities)
    definitions = (
        resolver.resolved_capability_definitions() if capabilities else action_catalog
    )
    engine = DeterministicEngineV2(action_catalog, capabilities)
    legal: list[str] = []
    for definition in definitions:
        if not actor_allowed(player, definition):
            continue
        package = ActionPackage(
            actor_id=player_entity_id,
            action_id=definition.action_id,
            capability_id=definition.capability_id,
            target_ids=default_targets(world_state, player_entity_id, definition),
            channel=default_channel(definition),
            intent_summary=definition.title,
            parameters={},
            submitted_turn=world_state.turn_number,
        )
        if engine.validate_action(world_state, package).is_valid:
            mechanical_id = definition.capability_id or definition.action_id
            if mechanical_id not in legal:
                legal.append(mechanical_id)
    return legal


def _validated_recommendations(
    proposed: list[str],
    *,
    legal_capability_ids: list[str],
    action_budget: int,
) -> list[str]:
    result: list[str] = []
    for capability_id in proposed:
        if capability_id in legal_capability_ids and capability_id not in result:
            result.append(capability_id)
        if len(result) >= action_budget:
            break
    return result


def _apply_reward(
    resources: dict[str, int],
    *,
    previous_plan_id: str,
    review_turn: int,
    resource: str,
    reason: str,
) -> ChiefAward | None:
    if not resource or resource not in resources:
        return None
    before = resources[resource]
    resources[resource] = before + 1
    return ChiefAward(
        plan_id=previous_plan_id,
        turn_number=review_turn,
        resource=resource,
        before=before,
        after=before + 1,
        reason=reason,
    )


def _fallback_response(
    previous: ChiefPlanState | None,
    legal_capability_ids: list[str],
    action_budget: int,
) -> ChiefPlanResponse:
    return ChiefPlanResponse(
        assessment="continue" if previous else "initial",
        assessment_summary=(
            "The Chief keeps the existing plan pending a clearer staff assessment."
            if previous
            else "The Chief establishes a cautious opening plan."
        ),
        objectives=(
            list(previous.objectives)
            if previous and previous.objectives
            else ["Create leverage while preserving a credible private off-ramp."]
        ),
        rationale=(
            previous.rationale
            if previous
            else "Controlled pressure and private contact preserve presidential options."
        ),
        recommended_capability_ids=legal_capability_ids[: max(action_budget, 0)],
    )


def _player_action_context(
    result: DeterministicTurnResult | None,
    *,
    player_entity_id: str,
) -> list[dict[str, str]]:
    if result is None:
        return []
    statuses = (
        ("accepted", result.accepted_actions),
        ("resolved", result.completed_pending_actions),
        ("rejected", result.rejected_actions),
    )
    return [
        {
            "status": status,
            "action_id": package.action_id,
            "capability_id": package.capability_id or "",
            "intent_summary": package.intent_summary,
        }
        for status, packages in statuses
        for package in packages
        if package.actor_id == player_entity_id
    ]


def _successful_player_actions(
    result: DeterministicTurnResult | None,
    player_entity_id: str,
) -> list[ActionPackage]:
    if result is None:
        return []
    return [
        package
        for package in [*result.accepted_actions, *result.completed_pending_actions]
        if package.actor_id == player_entity_id
    ]


def _chief_profile(world_state: WorldStateV2, player_entity_id: str) -> dict[str, object]:
    council = world_state.advisor_councils.get(player_entity_id)
    if council is None:
        return {}
    chief = council.advisors.get("personal")
    if chief is None:
        chief = next(
            (advisor for advisor in council.advisors.values() if advisor.loyal_to_player),
            None,
        )
    return chief.model_dump(mode="json") if chief else {}


def _remember_recommendation(
    world_state: WorldStateV2,
    player_entity_id: str,
    objectives: list[str],
) -> None:
    council = world_state.advisor_councils.get(player_entity_id)
    if council is None or not objectives:
        return
    chief = council.advisors.get("personal")
    if chief is None:
        return
    chief.recent_recommendations = [*chief.recent_recommendations, objectives[0]][-6:]


def _plan_id(turn_number: int, review_count: int) -> str:
    return f"chief_plan_{turn_number}_{review_count}"


def _label(value: str) -> str:
    return value.replace("_", " ").title()
