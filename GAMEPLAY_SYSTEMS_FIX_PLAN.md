# Gameplay Systems Fix Plan

Last rewritten: 2026-06-24

This is the current source-of-truth implementation plan for the text-first crisis room simulator. It incorporates the design answers from the previous open questions and the current repo-health review.

The project has a playable Serious Mode baseline for the Cuban Missile Crisis: briefings, advisor questions, plan preview/commit, multi-action player turns, NPC actions, deterministic adjudication, authored flash events, backchannels, advisor state updates, information routing, debug sessions, and a scripted offline LLM client.

The next work should not be a broad cleanup rewrite. The repo needs a short stabilization pass first, then the gameplay changes should drive targeted cleanup. A pure cleanup pass before the capability migration would churn the same files twice because the migration changes the core action interfaces.

## Current Verification Snapshot

Verified on 2026-06-24 with the documented conda environment:

```powershell
C:\Users\User\Miniconda3\Scripts\conda.exe run -n polmil python -m pytest tests -q -p no:cacheprovider
```

Result:

```text
77 passed, 4 skipped
```

The ambient `C:\Python314\python.exe` does not have pytest installed, so it is not a useful test runner for this repo. Use the conda command above unless the development environment is changed deliberately.

## Repo Health Snapshot

Git state:

- The repository has no commits yet.
- Every project file is currently untracked.
- `.gitignore` already excludes Python cache files, local config, runtime output, saves, virtual environments, and build artifacts.
- This means there is no reliable diff baseline until the first intentional commit or snapshot is made.

Structural hotspots:

- `src/crisis_room/scenario/schema.py` is over 1,100 lines and contains the built-in Cuba scenario, action catalog, events, and advisor seeds.
- `src/crisis_room/app/presentation.py`, `engine/adjudication.py`, `app/advisor_updates.py`, `llm/scripted_client.py`, `app/backchannels.py`, `app/tui.py`, and `app/turn_orchestrator.py` are the main large modules.
- `state/saves.py`, `scenario/loader.py`, `engine/time.py`, and `scenario/historical_script.py` are placeholders.
- Cooldowns are not just cosmetic. They exist in `ActionDefinition`, deterministic validation, metadata, batch validation, scenario data, and tests.
- Scenario-specific action IDs are used throughout the engine-facing catalog, tests, scripted client, presentation, events, advisor updates, and backchannel logic.

Conclusion:

Do a narrow hygiene checkpoint before more gameplay modifications. Then make cleanup part of each feature slice. Do not run a sweeping style/layout cleanup before the action/capability migration.

## Phase 0 - Stabilization And Cleanup Gate

This phase should happen before gameplay code changes.

Goals:

- Establish a version-control baseline.
- Preserve the current passing test state.
- Remove ambiguity about generated files and local-only config.
- Avoid broad refactors before the capability migration changes interfaces.

Tasks:

1. Run the conda pytest command and record the result.
2. Inspect ignored/generated files before any deletion. Keep `output/`, `saves/`, `__pycache__/`, `.pytest_cache/`, and local config out of git.
3. Make an initial commit or equivalent snapshot containing the current source, docs, tests, config examples, and scenario files.
4. Add a short developer note or README section naming the supported test command and the expected local config file.
5. Keep formatting-only edits out of the first gameplay migration unless they are in files already being changed.
6. Create a cleanup ledger for large files. Do not split them until the relevant phase touches their behavior.

Cleanup gates for every later phase:

- The conda test suite must pass before and after the phase.
- Any touched module over roughly 500 lines should either be reduced, given a clear follow-up split task, or left with a reason.
- Remove dead compatibility code when its replacement is complete.
- Avoid adding new scenario-specific mechanics to generic engine modules.
- Keep debug visibility separate from player-facing visibility.

## Binding Design Decisions

These decisions replace the previous open questions.

### Agenda And Turns

- The player action budget stays a soft design budget, not rigid slot types.
- The normal prompt-enforced budget remains three formal actions for pacing.
- If the player describes more than the normal budget, the system should give clear feedback about which intents were compiled, unprocessed, or rejected.
- Agenda slot violations should generally be warnings, but excessive action counts should hard reject instead of silently truncating.
- NPC factions should keep submitting one formal action each for readability.
- `PLAN` should preview all data legitimately available to the player, including known pending actions and visible flash-event risk.
- Saved playable sessions should restore a pending uncommitted plan.

### Actions And Capabilities

- Old scenario-specific action IDs should not remain as long-term aliases.
- The migration to generic actions plus scenario capabilities is allowed to be breaking for current saves and tests.
- Temporary bridge code is acceptable inside a short migration branch, but the completed phase should remove the old action IDs from normal gameplay.
- Action cooldowns should be removed. Repetition pressure should come from resources, preconditions, opportunity costs, event pressure, and scenario state.
- `ActionPackage.parameters` should be strict per capability. No freeform mechanical parameters.
- Generic actions own shared validation shape and broad defaults.
- Scenario capabilities own most scenario-specific preconditions, resource costs, effects, event hooks, message budgets, and player-facing affordance text.
- Action cards should show merged action/capability affordances, not raw generic primitives alone.

### Advisors

- Advisor numeric state should be invisible in normal play and visible only in debug output.
- Corruption and institutional capture should be hinted qualitatively when relevant, not exposed as normal numeric UI.
- LLM advisor responses may propose advisor state deltas, but this must happen inside an existing advisor/council response step rather than as a new LLM call.
- Proposed deltas must be deterministically clamped and validated before touching state.
- Inter-advisor trust should strongly affect advice tone and council reads. High trust should produce less divisive guidance and lower political churn. Low trust should produce sharper disagreement and conditional-sounding advice in prose, without implementing formal conditional-action mechanics yet.
- Advisor embarrassment and memory should affect future dialogue style.

### Backchannels

- Some direct backchannel messages should advance the turn.
- Message budgets should be owned by capabilities.
- Direct messages should use a bounded LLM counterpart response contract.
- A direct message can be as impactful as a full action and should be able to trigger the same deterministic update pipeline when marked as formal.
- Leaked backchannel messages should be able to trigger authored flash events when the scenario defines one.

### Events

- Major flash events can be authored or LLM-proposed, but LLM proposals must pass deterministic approval before they affect mechanics.
- This hybrid exists mainly for drift, where authored flashpoints no longer fit the current scenario state.
- Multiple events may fire in a turn, or none. Event density should depend on escalation, recent action density, scenario settings, and approved event candidates.
- Event definitions decide whether immediate player choices are available.
- The default should be no immediate choice, because emergency choices can become free actions.
- When emergency choices exist, they should consume the normal action budget where possible and may also grant explicit event-only extra budget.
- Event history should be stored in the timeline. Normal briefings should show only the most recent or currently relevant events for now.

### Endings

- Remove the final scorecard concept from the roadmap.
- Endings should be scenario-specific conditions generated or defined at scenario setup.
- For the Cuban Missile Crisis, likely ending conditions include settlement reached, nuclear war, or an unstable continuation state.
- The player should not see a likely ending trajectory before the crisis ends.
- Private deals, leaks, unresolved issues, and hidden clocks should shape the final timeline and ending summary, not a numeric score.
- An ending should be emitted as a special event. The player can accept it or reject it and continue.
- If the player rejects an ending, the same ending should not be offered again for three turns.

### Saves And Scenarios

- `schema_version` can remain a label for now. Do not build a full migration layer until a breaking save format needs to be supported across versions.
- Debug sessions and playable saves should be separate file types.
- Externally-authored scenario validation will be designed later with a scenario builder module.
- Scenarios should load at launch only for now.

## Phase 1 - Capability Migration, With Targeted Cleanup

This is the next major implementation phase after Phase 0.

Why it comes first:

- It removes the biggest architectural blocker.
- It lets Serious Mode, future Game Mode proposals, backchannels, events, and generated scenarios share the same action spine.
- It avoids building more behavior on top of Cuba-specific engine action IDs.
- It is the right time to remove cooldowns because action identity and resource validation are changing anyway.

Definition of done:

- All normal player and NPC actions use generic action IDs plus scenario capability IDs.
- Old scenario-specific action IDs are removed from normal compiled gameplay, scripted gameplay, scenario events, advisor updates, and tests.
- No action cooldown validation, cooldown metadata, cooldown batch warning, or scenario cooldown field remains.
- Capabilities validate strict parameter shapes.
- Action cards render merged action/capability choices.
- The conda test suite passes.

Implementation tasks:

1. Add generic action primitives, for example: `public_statement`, `private_diplomacy`, `backchannel_message`, `military_posture`, `reconnaissance`, `covert_operation`, `information_operation`, `inspection_offer`, `third_party_mediation`, and `military_deconfliction`.
2. Add a `ScenarioCapability` model with `capability_id`, `generic_action_id`, owner/actor rules, target rules, channel rules, strict parameter schema reference or validator, resource requirements, resource costs, scenario effects, prompt hints, player card text, event hooks, and optional message budget settings.
3. Add `Scenario.capabilities`.
4. Change `ActionPackage` so `action_id` is generic, `capability_id` is required for scenario capabilities, and `parameters` is a strict dictionary validated through the capability registry.
5. Introduce a resolver that combines generic action defaults with capability mechanics into the engine-facing resolved action.
6. Port the Cuban player actions into capabilities: quarantine announcement, private Kremlin channel, public withdrawal demand, reconnaissance overflights, DEFCON readiness, non-invasion pledge, secret Jupiter trade, and air strike preparation.
7. Port NPC actions into capabilities: Soviet compromise probe, Soviet public defiance, Cuban air defense alert, and NATO reassurance pressure.
8. Update `CatalogGamemasterCompiler`, prompt contracts, and the scripted client to emit generic action plus capability plus strict parameters.
9. Update action cards, plan previews, batch warnings, debug transcripts, scenario events, advisor updates, and backchannel updates to refer to capability IDs.
10. Remove `cooldown_turns`, `skip_cooldown`, `_cooldown_key`, `_set_cooldown`, duplicate cooldown warnings, and cooldown tests.
11. Replace cooldown tests with resource/precondition/opportunity-cost tests.
12. Split `scenario/schema.py` only as needed while porting capabilities. A good target is a built-in Cuba scenario package with separate files for entities, capabilities, events, and advisors.

## Phase 2 - Agenda, PLAN, And Playable Saves

This phase makes the freeform Serious Mode loop clearer and less lossy.

Definition of done:

- The compiler no longer silently truncates extra player intents.
- The player sees clear feedback for compiled, rejected, and unprocessed intents.
- `PLAN` previews all player-known consequences and risks available before turn resolution.
- Pending uncommitted plans survive playable save/load.
- NPCs still submit one action each.

Implementation tasks:

1. Replace `MultiIntentCompilation` hard truncation with explicit normal budget and hard maximum behavior.
2. Add player-facing unprocessed-intent feedback.
3. Make the action budget configurable, defaulting to three.
4. Keep structured slots out of the engine for now. Use warnings for odd agenda shape rather than hard one-major/one-diplomatic/one-staff slots.
5. Extend `PlayerPlanPreview` with known pending actions, resource pressure, open backchannel constraints, recent event context, and visible flash-event risks.
6. Keep `PLAN` player-visible. Do not reveal hidden clocks, private NPC intent, or event probabilities unless they are legitimately known.
7. Implement playable save artifacts separately from debug sessions.
8. Persist and restore a pending uncommitted plan when the saved world still matches its turn and state fingerprint.
9. Clean up `state/saves.py` as part of this phase.

## Phase 3 - Backchannel Upgrade

This phase turns backchannels from mostly pre-turn utility into capability-owned crisis actions.

Definition of done:

- Backchannel-opening and backchannel-message behavior is capability-driven.
- Message budgets come from capabilities.
- Formal direct messages can advance the turn and resolve through the normal action pipeline.
- A bounded LLM counterpart response contract exists.
- Leaks can trigger scenario-authored flash events.

Implementation tasks:

1. Model direct backchannel messages as `backchannel_message` capabilities when they are mechanically significant.
2. Keep lightweight inspection commands such as `BACKCHANNELS` outside turn resolution.
3. Decide in validation whether a direct message is informal or a formal action that advances the turn.
4. Add a counterpart response contract with strict fields and bounded text.
5. Route formal direct messages through deterministic effects, info routing, advisor updates, relationship updates, backchannel state, and event checks.
6. Move hard-coded message budgets into capability definitions.
7. Add event hooks for leaked backchannel messages.
8. While touching `app/backchannels.py`, reduce duplicate helper logic shared with advisor updates where it is easy and low-risk.

## Phase 4 - Advisor Council Contract

This phase makes advisors stable game entities instead of mostly generated voices.

Definition of done:

- Advisor responses use stable advisor IDs.
- Invented advisors are rejected.
- Advisor numeric state remains debug-only.
- Advisor memory, embarrassment, and inter-advisor trust influence dialogue style and council reads.
- LLM-proposed advisor deltas are optional, bounded, and applied by deterministic clamps.

Implementation tasks:

1. Add `advisor_id` to `AdvisorView`.
2. Add `AdvisorCouncilResponse` with advisor views, council summary, suggested capabilities, risk warnings, information gaps, and optional proposed deltas.
3. Require all advisor IDs to come from the scenario council.
4. Include recent recommendations, embarrassment/memory, and trust relationships in bounded prompt context.
5. Add deterministic validation and clamping for proposed advisor deltas.
6. Apply accepted deltas in the existing advisor update step, not a new LLM step.
7. Update TUI rendering so normal play shows qualitative advisor movement while debug mode shows numbers.
8. Add tests for no invented advisors, debug-only numeric state, clamped deltas, memory-influenced wording, and inter-advisor trust effects.

## Phase 5 - Event System Expansion

This phase keeps authored events but adds controlled drift handling and player choice support.

Definition of done:

- More than one event can fire in a turn when the scenario allows it.
- LLM-proposed events can be approved or rejected deterministically.
- Event choices can exist without becoming free actions.
- Event history is persisted and rendered through the timeline, with normal briefings showing only current or recent relevant events.

Implementation tasks:

1. Add event density settings based on escalation, action density, and scenario configuration.
2. Replace the fixed one-event default with scenario-configurable max events.
3. Narrow `EventCreatorAgent` into event framing plus bounded event candidate proposal.
4. Add deterministic approval for LLM event candidates.
5. Add event choice/option models.
6. Mark whether an event choice consumes normal budget, grants event-only extra budget, or both.
7. Persist unresolved event choices if the player does not answer immediately.
8. Route event choices through capabilities rather than bespoke mechanics.
9. Keep authored event definitions in Python until the capability and event schemas settle.

## Phase 6 - Endings Without Scorecards

This phase replaces scorecards with scenario-specific ending events and timeline summaries.

Definition of done:

- No `EndingScorecard` roadmap item remains.
- Existing outcome evaluation is either repurposed for ending-event eligibility or replaced by a clearer ending evaluator.
- Endings are emitted as special events.
- The player can accept an ending or reject it and continue.
- Rejected endings use a three-turn reoffer delay.

Implementation tasks:

1. Add scenario ending definitions with scenario-specific conditions.
2. Use the current `engine/outcomes.py` only if it cleanly maps to ending eligibility. Otherwise replace it with an ending-event evaluator.
3. Add ending event records to the timeline.
4. Add accept/reject handling for ending events.
5. Store ending acceptance, rejection, and reoffer delay in world state.
6. Generate final summaries from the timeline and known unresolved issues.
7. Do not expose likely ending trajectory during normal play.
8. Update `PIPELINE_MODES_SERIOUS_AND_GAME.md` so it no longer promises ending scorecards.

## Phase 7 - Scenario Loading And Builder Preparation

This phase prepares for external scenarios without trying to build the whole scenario-authoring product at once.

Definition of done:

- Built-in scenarios still load at launch.
- A minimal scenario loader exists for launch-time loading.
- Playable saves and debug sessions remain separate.
- `schema_version` remains a label unless there is a concrete migration need.

Implementation tasks:

1. Implement `scenario/loader.py` for launch-time scenario selection.
2. Keep hot-loading out of scope.
3. Validate IDs, actor references, capability references, event references, and ending references at load time.
4. Keep externally-authored scenario files minimal until the schema stabilizes.
5. Leave the full scenario builder module for a later phase.
6. Update docs so generated scenarios mention capabilities and ending events, not scorecards.

## Phase 8 - Contract Hardening And Context Budgets

This phase prevents the LLM layer from quietly widening the mechanics.

Definition of done:

- New contracts have strict validators.
- Prompt context budgets are explicit and tested.
- Debug sessions record raw and parsed outputs for every new contract.
- Player-facing output avoids hidden-state leakage.

Implementation tasks:

1. Add stricter Pydantic validators where coercion could hide bad output.
2. Bound context for event history, advisor beliefs, active capabilities, active threads, inbox, public timeline, action cards, and proposals.
3. Add retry handling for new contracts where appropriate.
4. Keep raw and parsed outputs in debug sessions.
5. Add prompt-contract tests for each new schema.
6. Audit player-facing rendering after each new contract.

## Later Track - Game Mode

Game Mode remains a later interaction layer, not part of the immediate Serious Mode repair work.

Do not start Game Mode before the generic action/capability migration is stable. Its proposal cards should be built on the same capability system rather than on temporary scenario-specific action IDs.

First useful Game Mode slice after the shared core is ready:

- Config-backed `gameplay.mode`, defaulting to `serious`.
- Deterministic proposal cards derived from capabilities.
- Visit at least State, Defense, and Intelligence rooms.
- Endorse/promote proposals into the same action package pipeline.
- Pushback/defer recorded with bounded advisor/proposal effects.
- Existing Serious Mode behavior preserved.

## Safety And Tone Boundaries

The game may model sabotage, covert pressure, leaks, military posture, and crisis bargaining as abstract political-military choices. It should not provide procedural real-world harm details. Mechanics should stay at the level of scenario decisions, institutional effects, information flow, and strategic consequences.
