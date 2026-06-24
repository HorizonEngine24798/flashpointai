# Pipeline Modes: Serious Mode and Game Mode

Status: proposed architecture direction with current-implementation notes.

Last clarified: 2026-06-24

This document describes a two-mode design for the crisis simulator.

The core idea:

```text
Same deterministic engine.
Same scenario/state model.
Same LLM-capable pipeline.
Different player interaction modes.
```

The game should default to **Serious Mode**, which is closer to the current crisis-room simulator proposal. A config file can eventually switch to **Game Mode**, which uses the newer proposal-driven interaction model.

Important current-state note:

```text
The implemented game today is Serious Mode only.
Game Mode is a proposed interaction layer, not a shipped command loop.
```

`GAMEPLAY_SYSTEMS_FIX_PLAN.md` is the source of truth for the current playable systems and near-term gameplay fixes. This document explains how those systems should support two different player-facing modes.

## Why Two Modes

There are two promising products hiding inside the same codebase.

Serious Mode is better for:

- simulation credibility,
- freeform strategic expression,
- research/project appeal,
- GitHub presentation,
- demonstrating the LLM-agent pipeline,
- historical or educational use.

Game Mode is better for:

- Steam-style playability,
- fast decisions,
- replayability,
- UI clarity,
- lower player writing burden,
- deterministic balance,
- stronger moment-to-moment game feel.

These should not become two unrelated projects. They should be two front doors into the same underlying crisis engine.

## Shared Core

Both modes should share:

- deterministic action validation,
- deterministic action resolution,
- resources,
- clocks,
- public metrics,
- hidden truth metrics,
- relationships,
- advisor state,
- backchannel state,
- scenario events,
- information distortion,
- timelines,
- after-action reports,
- ending scorecards.

The LLM can still exist in both modes, but its authority differs by mode.

Important invariant:

```text
The LLM may generate context, proposals, dialogue, summaries, and flavor.
The deterministic engine owns legality, effects, clocks, resources, and outcomes.
```

## Current Implemented Gameplay

The current repo already has a playable text-first Cuban Missile Crisis loop. It is not Game Mode yet; it is the Serious Mode baseline.

Current implemented loop:

```text
Briefing
  -> problems on the table
  -> qualitative pressure indicators
  -> council read
  -> action cards as hints
  -> optional ASK advisor dialogue
  -> optional PLAN preview
  -> ACTION, COMMIT, or END
  -> NPC faction actions and ambient event framing
  -> deterministic action resolution
  -> authored scenario flash events
  -> information routing, leakage, delay, and distortion
  -> backchannel updates
  -> advisor state updates
  -> player-facing results
  -> updated briefing for the next turn
```

Implemented player verbs:

- `ASK <text>` asks advisors without advancing the turn.
- `PLAN <text>` compiles up to three player actions and shows warnings without advancing the turn.
- `COMMIT` advances the turn using the last compiled plan.
- `ACTION <text>` compiles and immediately advances one turn.
- `END` advances one turn with no formal player action.
- `BACKCHANNEL <target> <message>` sends a direct message through an already open thread without advancing the turn.

Current important behavior:

- One player turn can include up to three formal player actions.
- The three-action budget is a simple cap, not a structured slot system.
- NPC factions currently submit at most one formal action each.
- Advisor suggestions and action cards are informational; they are not selectable proposal objects.
- Batch warnings are advisory unless the deterministic engine rejects an action.
- The deterministic engine remains authoritative for legality, costs, cooldowns, preconditions, targets, scheduling, and effects.

What this means for the confusing verbs:

```text
Promote / endorse / push back / defer are not implemented commands today.
They belong to the proposed Game Mode layer.
```

## Serious Mode

Serious Mode is the default.

This mode keeps the current text-first crisis-room fantasy:

```text
Ask advisors
  -> type freeform questions
  -> submit freeform action text
  -> LLM compiles intent
  -> deterministic engine validates and resolves
  -> advisors/NPCs/events update
  -> after-action report
```

Serious Mode should support:

- freeform `ASK`,
- freeform `ACTION`,
- multi-action turns,
- advisor dialogue,
- backchannel messages,
- LLM faction agents,
- LLM event framing,
- scenario-specific briefings,
- debug transcripts.

The player can still receive action cards and briefings, but they are aids rather than the primary input method.

Serious Mode should feel like:

```text
I am inside a crisis room, reasoning through ambiguous information and issuing my own instructions.
```

### Serious Mode Player Verbs

Primary verbs:

- ask,
- plan,
- action,
- backchannel,
- status,
- end turn.

The player is allowed to type original policy intent. The system tries to translate it into legal action packages.

### Serious Mode LLM Role

In Serious Mode, the LLM can:

- answer advisor questions,
- simulate faction deliberation,
- compile player intent,
- propose NPC actions,
- frame events,
- write public/private signal wording,
- summarize after-action narrative.

But the LLM still cannot directly mutate state.

### Serious Mode Fix Track

The current gameplay fixes mostly strengthen Serious Mode and the shared core that Game Mode will reuse.

Near-term fixes from the current gameplay roadmap:

- keep the current `ASK` / `PLAN` / `COMMIT` / `ACTION` loop stable;
- make the generic action and scenario capability layer so actions are no longer hard-wired to Cuban Missile Crisis-specific IDs;
- port NPC and player actions from scenario-specific IDs to generic actions plus scenario capabilities;
- upgrade advisor dialogue so advisor responses use stable advisor IDs and persistent advisor state more directly;
- add event choices for major flash events instead of only automatic interruptions;
- add ending scorecards;
- implement a real save schema and scenario loader;
- harden prompt contracts and context size limits.

These fixes are not Game Mode by themselves. They are the foundation Game Mode needs:

```text
capabilities make proposals reusable across scenarios
advisor IDs make proposal ownership stable
event choices give Game Mode urgent cards
scorecards make fast play legible
saves and loaders make mode switching durable
```

## Game Mode

Game Mode is the more commercial, Steam-friendly interaction layer.

This mode limits the player's primary interaction to proposal management:

```text
Visit advisor, faction, backchannel, or news source
  -> see 2-3 proposed actions
  -> endorse, push back, or defer
  -> endorsed proposals form a turn agenda
  -> deterministic engine resolves the agenda
  -> advisor/faction/channel state changes
  -> next briefing
```

The player can still manually type in limited places, but typing is secondary. The main loop is fast, constrained, and card-like.

Game Mode should feel like:

```text
I am managing a dangerous political machine by choosing which people, institutions, and risks to empower.
```

### Game Mode Status

Game Mode is not implemented yet.

Missing pieces:

- visitable rooms;
- proposal card models;
- proposal generation;
- proposal ownership by advisor, faction, backchannel, news source, or institution;
- `endorse` / `promote`;
- `push back`;
- `defer`;
- visit or attention budgets;
- proposal-pool updates;
- routing endorsed proposals into player action packages without freeform compilation.

The current action cards and advisor `suggested_action_ids` are useful ingredients, but they are not Game Mode proposals yet.

### Game Mode Turn Model

The intended Game Mode loop should be:

```text
Briefing
  -> choose a room/source to visit
  -> inspect 2-3 proposal cards
  -> endorse/promote, push back, defer, or request alternative
  -> repeat until visits or attention are spent
  -> resolve the endorsed agenda through the shared deterministic engine
  -> events, routing, backchannels, advisors, and NPCs update
  -> results
  -> next briefing
```

This keeps Game Mode on the same mechanical spine as Serious Mode:

```text
proposal card -> endorsed proposal -> ActionPackage -> deterministic engine
```

The important design preference is that proposal cards should replace freeform player compilation as the normal Game Mode input. Freeform text can still exist for pushback, backchannel messages, or optional advanced play, but it should not be the main action path.

### Proposal Semantics

A Game Mode proposal should be a first-class object, not just display text.

Minimum proposal fields:

- stable proposal ID;
- source type, such as advisor, faction, backchannel, news source, or institution;
- source ID, such as `state`, `defense`, `intelligence`, or `kremlin_backchannel`;
- title and player-facing summary;
- action ID or capability ID;
- target IDs;
- channel;
- expected pressure summary;
- risk summary;
- known costs;
- hidden or debug-only rationale;
- expiration or refresh rule;
- status, such as available, endorsed, pushed_back, deferred, expired, or resolved.

`endorse` or `promote` should mean:

```text
The player gives this proposal presidential backing.
The proposal becomes a candidate player action package.
The source gains political weight or trust if the action is coherent and accepted.
The deterministic engine still decides legality and effects.
```

`push back` should mean:

```text
The player challenges the proposal without submitting it as a formal action.
The source may revise, harden, lose confidence, lose trust, or offer an alternative.
The proposal pool changes, but world mechanics should mutate only through bounded rules.
```

`defer` should mean:

```text
The player declines to spend attention or authority on the proposal right now.
The proposal may remain available, decay, expire, or be replaced depending on source pressure.
```

If the player promotes several proposals in one Game Mode turn, those proposals should enter the same shared batch-validation and deterministic-resolution path used by Serious Mode. The current shared engine can already handle multiple player action packages, but Game Mode still needs to decide whether its budget is:

- exactly the current three-action cap;
- structured slots such as one major, one diplomatic, one staff task;
- a visit or attention budget that indirectly limits actions;
- immediate one-proposal resolution after each endorsement.

### Game Mode Player Verbs

Primary verbs:

- visit,
- endorse or promote,
- push back,
- defer,
- inspect,
- end turn.

Possible secondary verbs:

- request alternative,
- pin proposal,
- spend extra attention,
- open backchannel,
- compare proposals.

### Game Mode LLM Role

In Game Mode, the LLM can:

- generate proposal text,
- explain why an advisor wants a proposal,
- write faction-facing flavor,
- interpret a player's typed pushback if typing is enabled,
- help create a scenario during pregame setup.

But the LLM should not compile arbitrary player policy text into unlimited actions during normal play.

The key difference:

```text
Serious Mode:
  player text -> LLM intent compiler -> action package

Game Mode:
  LLM/logic proposal generator -> player endorsement -> action package
```

## Pregame Scenario Warmer

Both modes can use a pregame scenario warmer.

The player describes a crisis premise:

```text
1971 India-Pakistan crisis from Nixon's White House.
```

or:

```text
An alternate 1983 Able Archer escalation from the Soviet Politburo.
```

The warmer asks the LLM to produce a structured scenario package:

- scenario title,
- historical period,
- player faction,
- opposing factions,
- allied factions,
- international/community actors,
- advisors,
- internal faction narratives,
- starting resources,
- public metrics,
- hidden clocks,
- scenario issues,
- capabilities,
- plausible events,
- ending scorecard dimensions.

Then deterministic validators check and clamp the generated scenario:

- all IDs are stable,
- all actors have valid types,
- all capabilities map to generic action primitives,
- resources are within allowed ranges,
- clocks and metrics are bounded,
- events have deterministic effects,
- no event can create unsupported mechanics,
- endings have computable conditions.

The warmer is what preserves the major advantage of the LLM pipeline:

```text
The player can load many different crisis premises without the developer hand-authoring every scenario.
```

## Generated Scenario, Constrained Play

The ideal hybrid is:

```text
LLM-authored setup.
LLM-assisted actor flavor.
Constrained player action space.
Deterministic resolution.
```

This can support both modes:

- Serious Mode allows more freeform player instruction.
- Game Mode turns the same generated scenario into proposal cards and institutional pressure.

The scenario can be flexible. The mechanics remain bounded.

## Config File

Mode selection should live in config, not in hard-coded branches.

Example:

```json
{
  "gameplay": {
    "mode": "serious",
    "max_player_actions_per_turn": 3,
    "show_action_cards": true,
    "show_qualitative_pressure": true,
    "debug_visibility": "player"
  },
  "llm": {
    "provider": "llama_cpp",
    "model": "local-qwen",
    "base_url": "http://127.0.0.1:8080/v1",
    "temperature": 0.4,
    "scenario_warmer_enabled": true,
    "runtime_actor_generation": true
  },
  "scenario": {
    "source": "built_in",
    "scenario_id": "cuban_missile_crisis_1962",
    "allow_generated_scenarios": false
  },
  "game_mode": {
    "visits_per_turn": 2,
    "proposals_per_visit": 3,
    "allow_manual_text_pushback": true,
    "allow_freeform_action": false
  },
  "serious_mode": {
    "allow_freeform_ask": true,
    "allow_freeform_action": true,
    "allow_plan_preview": true,
    "proposal_cards_are_hints": true
  }
}
```

Default:

```json
{
  "gameplay": {
    "mode": "serious"
  }
}
```

The same config file can later control other pipeline knobs:

- LLM provider,
- model path or model name,
- base URL,
- temperature,
- context limits,
- debug verbosity,
- scenario source,
- generated scenario permission,
- number of proposals,
- action budget,
- event frequency,
- hidden clock visibility,
- save directory.

## Mode-Specific Interface

### Serious Mode Interface

Example:

```text
TURN 3: October 24, Morning

Pressure:
- Escalation: dangerous, rising
- Backchannel viability: fragile, falling

Council read:
- State says the off-ramp is still open.
- Defense says delay is becoming unacceptable.

Commands:
ASK <text>
PLAN <text>
ACTION <text>
BACKCHANNEL <target> <message>
END
```

### Game Mode Interface

Example:

```text
TURN 3: October 24, Morning

Visits remaining: 2

Available rooms:
1. State Department
2. Defense
3. Intelligence
4. Public News
5. Kremlin Backchannel
```

After visiting State:

```text
STATE DEPARTMENT

1. Open private Kremlin backchannel
   Expected effect: off-ramp up
   Risk: leak risk

2. Offer non-invasion pledge
   Expected effect: Cuban invasion fear down
   Risk: domestic hawks harden

3. Ask for a lower-publicity diplomatic probe
   Expected effect: preserves resources
   Risk: backchannel window narrows

Choose: endorse 1, push back, defer, return
```

## Shared Scenario Output, Different Rendering

The same scenario state can render differently by mode.

Same underlying state:

```text
backchannel_viability = 0.42
defense_urgency = 0.78
public_alarm = 0.61
```

Serious Mode rendering:

```text
Advisors warn that the private channel is weakening. Defense is pressing hard for readiness measures.
```

Game Mode rendering:

```text
State Department proposal pool weakened.
Defense proposal pool intensified.
Public News pressure rising.
```

## Implementation Strategy

Do not fork the engine.

Add a mode layer above the existing orchestrator:

```text
Config
  -> mode controller
  -> serious interaction controller OR game interaction controller
  -> shared orchestrator services
  -> deterministic engine
```

Shared services:

- briefing builder,
- action card builder,
- proposal generator,
- advisor updater,
- event resolver,
- backchannel manager,
- after-action report builder,
- scorecard evaluator.

Mode-specific services:

- freeform intent compiler for Serious Mode,
- visit/proposal selector for Game Mode,
- command parser,
- rendering style.

## Migration Path

Recommended sequence:

1. Add config-backed `gameplay.mode`, defaulting to `serious`.
2. Preserve current text interface under Serious Mode.
3. Keep action cards and qualitative pressure as Serious Mode hints.
4. Finish the generic action and scenario capability compatibility layer.
5. Add a first-class Game Mode proposal model.
6. Add a proposal generator using the existing action catalog, advisor state, backchannel state, and later capabilities.
7. Add a room/source model for visits.
8. Add Game Mode TUI loop with visits, proposal inspection, endorse/promote, push back, defer, and end turn.
9. Route endorsed proposals into the same deterministic engine as precompiled player action packages.
10. Add batch validation rendering for promoted proposal combinations.
11. Add bounded pushback/defer state changes.
12. Add event choice cards and ending scorecards.
13. Add pregame scenario warmer once generic actions/capabilities are stable.
14. Add generated scenario validation and repair.
15. Let both modes load built-in or generated scenarios.

This avoids betting the whole project on the pivot before it proves itself.

### First Game Mode Slice

The smallest useful Game Mode implementation should not try to replace the whole simulator.

Definition of done for the first slice:

- Game Mode can be selected by config or command-line flag.
- The player can visit at least three rooms: State, Defense, and Intelligence.
- Each room shows 2-3 deterministic proposal cards derived from the existing action catalog.
- The player can endorse one or more proposals into a turn agenda.
- Endorsed proposals resolve through the existing deterministic engine.
- Promoting more than the allowed budget produces a clear warning or rejection.
- Pushback and defer are recorded, even if their first implementation only changes proposal availability and advisor trust in small bounded ways.
- Existing Serious Mode tests and behavior remain intact.

## Open Questions

### Mode Boundary

1. Should `GAMEPLAY_SYSTEMS_FIX_PLAN.md` remain strictly about implemented/current gameplay while this document owns Game Mode design?
2. Should Game Mode launch only after the generic capability layer exists, or can it start with current scenario-specific action IDs?
3. Should Serious Mode and Game Mode have separate save compatibility flags?
4. Should a saved game remember the active mode, or should the same world state be reopenable in either mode?

### Turn and Agenda

1. Does Game Mode resolve immediately after each endorsement, or does it build an endorsed agenda and resolve at end turn?
2. Should Game Mode reuse the current three-action cap exactly?
3. Should Game Mode use structured slots such as one major, one diplomatic, and one staff task?
4. Should visits and formal actions be the same budget, or should visits only control information/proposal access?
5. Should visits consume budget when the player returns with no endorsement?
6. What happens when the player promotes every visible proposal: hard cap, warnings, auto-prioritization, or forced choice?

### Proposal Generation

1. Should proposal generation be deterministic, LLM-driven, or hybrid by config?
2. Should proposal cards be generated from action cards, advisor state, faction pressure, backchannel threads, event records, or all of them?
3. Should each advisor have a persistent proposal pool, or should proposals be regenerated fresh each visit?
4. Should proposal cards expose generic actions, scenario capabilities, or merged action/capability affordances?
5. Can two rooms propose the same underlying action with different framing and consequences for advisor trust?
6. How long does a proposal stay valid before it expires or changes?

### Endorse / Promote

1. Is `promote` just a synonym for `endorse`, or should promote mean giving a source extra institutional authority?
2. Does endorsement always create a player `ActionPackage`, or can some proposals create direct messages, event choices, or staff tasks?
3. Does endorsement mutate advisor trust immediately, only after deterministic acceptance, or only after visible results?
4. If an endorsed proposal is rejected by the engine, should the proposing advisor lose trust, the player lose authority, or neither?
5. If multiple endorsed proposals conflict, should Game Mode show warnings and let the player proceed, or block the agenda until it is cleaned up?

### Pushback and Defer

1. Is pushback a freeform text field, a small menu of objections, or both?
2. Should pushback consume a visit or attention point?
3. Should pushback only change the proposal pool, or can it mutate advisor trust, urgency, paranoia, and institutional confidence?
4. Can pushback create a revised proposal in the same visit?
5. Can repeated pushback make an advisor stop offering certain classes of proposals?
6. Should defer be neutral, or should ignored high-pressure proposals decay, intensify, or embarrass their source?

### Advisors and Institutions

1. How visible should advisor numeric state be in Game Mode?
2. Should proposal cards show the advisor/source motivation, or only the expected effects and risks?
3. Should inter-advisor trust affect which proposals appear together?
4. Should advisor embarrassment and memory change proposal wording and future proposal pools?
5. Should corruption or institutional capture be debug-only, hinted qualitatively, or surfaced as a Game Mode pressure system?

### Backchannels

1. Is a backchannel visit a room like State or Defense, or a separate scarce action?
2. Can a backchannel proposal be endorsed into a formal action, a direct message, or both?
3. Should Game Mode direct messages advance the turn, consume attention, or remain pre-turn interactions?
4. Should leaked backchannel proposals create authored flash events?
5. Should backchannel proposal availability depend on a thread being open, viable, and recently maintained?

### Events

1. Should flash events appear as forced proposal cards, separate emergency choices, or briefing problems?
2. Do emergency event choices consume the normal Game Mode agenda budget?
3. Should only one authored event fire per turn in Game Mode, as in the current implemented loop?
4. Can event pressure alter proposal pools before the player acts, or only after the turn resolves?

### Freeform Text

1. Should Game Mode allow any freeform `ACTION`, or only typed pushback/commentary?
2. Should typed pushback be interpreted by an LLM, deterministic tags, or both?
3. Should advanced players be able to open Serious Mode's `PLAN` preview inside Game Mode?
4. Should manual text be a config option, a difficulty option, or unavailable in Game Mode?

### Scenarios and Generated Content

1. Should generated scenarios be allowed in Serious Mode first, Game Mode first, or both at once?
2. Should the scenario warmer be allowed to generate new action capabilities, or only map to existing generic primitives?
3. How much generated scenario content should be saved and surfaced for debugging?
4. How should externally authored scenarios define proposal sources, rooms, advisor pools, events, and ending scorecards?

## Design Summary

Serious Mode keeps the original ambition:

```text
freeform crisis-room simulation powered by LLM agents and deterministic adjudication
```

Game Mode turns the same machinery into:

```text
proposal-driven crisis strategy with constrained choices and faster feedback
```

The default should remain Serious Mode. Game Mode can be enabled through config and developed as a parallel interaction layer.

This gives the project two paths:

- a stronger GitHub/AI-simulation showcase,
- a stronger Steam/gameplay product.

The best version may ultimately use both.
