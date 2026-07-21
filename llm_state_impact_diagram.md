# LLM State / Knob Impact

This complements [architecture_diagram.md](architecture_diagram.md) by showing
which model calls can change which parts of `WorldStateV2`, and which settings
constrain those changes.

```mermaid
flowchart LR
    UI[Player / UI]
    Turn[TurnOrchestrator.run_turn]

    subgraph LLM[LLM calls]
        Ask[Advisor Q&A\nAdvisorCouncilResponse]
        GM[Player compiler\nMultiIntentCompilation]
        Faction[NPC faction turn\nFactionTurnResponse]
        Intl[International pressure\nInternationalPressure]
        Event[Media / event creator\nEventCreatorResponse]
        Distort[Signal distortion\nSignalDistortionResponse]
        Reply[Backchannel reply\nBackchannelCounterpartResponse]
        BState[Backchannel state\nBackchannelStateChange]
    end

    subgraph DET[Deterministic gates and reducers]
        Engine[DeterministicEngineV2\nvalidation, resources, effects]
        Router[Info channel\ndelay, leak, distortion, delivery]
        Pressure[Scenario pressure\nrules and hidden obligations]
        Events[Scenario events\ntrigger checks and effects]
        Target[Backchannel target/thread validation]
        Posture[No-visible-player-move observation]
        Post[Post-turn updates\nadvisors, threads, endings]
    end

    subgraph STATE[WorldStateV2 knobs / state]
        Actor[Actor-local state\nbeliefs, memory, narrative influence,\nunresolved threads, resources]
        Metrics[Global metrics\ntruth_metrics, public_metrics]
        Clocks[Hidden clocks\nescalation, command risk,\nbackchannel viability]
        Relations[Relationships]
        Signals[Signals, inboxes,\npublic/entity timelines]
        Threads[Backchannel threads\ntrust, leak risk, messages]
        Advisors[Advisor councils\ntrust, urgency, beliefs]
        EventsState[Events, choices,\nending offers, pending actions]
    end

    subgraph KNOBS[Configuration / scenario knobs]
        Catalog[Action catalog + capabilities\nresource costs, channels,\nmetric/clock effects]
        PressureKnobs[Pressure rules + hidden obligations]
        ChannelKnobs[InfoChannelConfig\ndelay, leak, distortion]
        EventKnobs[Scenario event settings\nprobability, pressure thresholds]
        EndingKnobs[Ending definitions\nmetric/clock thresholds]
        PromptKnobs[Prompt text + schema guidance\nllm/prompts.py]
        BudgetKnobs[Budgets + context limits\nmax tokens, action limits]
    end

    UI --> Turn
    Turn --> Ask
    Turn --> GM
    Turn --> Faction
    Turn --> Intl
    Turn --> Event

    Ask -. advice / proposed deltas .-> Advisors
    Ask -. suggested actions only .-> UI
    GM --> Engine
    Faction --> Engine
    Faction -. beliefs, memory, questions,\nnarrative arguments/influence .-> Actor
    Intl --> Router
    Event --> Events

    Engine --> Router
    Engine --> Metrics
    Engine --> Clocks
    Engine --> Relations
    Engine --> EventsState
    Router -. distorted signal .-> Distort
    Distort -. observed wording only .-> Router
    Router --> Signals
    Router --> Actor
    Router --> Threads
    Router --> Posture
    Posture --> Actor

    Pressure --> Metrics
    Pressure --> Clocks
    Pressure --> Relations
    Events --> Router
    Events --> EventsState
    Events --> Metrics
    Events --> Clocks
    Events --> Signals
    Post --> Advisors
    Post --> Threads
    Post --> EventsState

    UI --> Target
    Target --> Reply
    Reply --> BState
    BState --> Actor
    Reply --> Threads
    Reply --> Relations
    Reply --> Signals

    Catalog -. constrains .-> GM
    Catalog -. validates .-> Faction
    Catalog -. drives effects .-> Engine
    PressureKnobs -. drives .-> Pressure
    ChannelKnobs -. drives .-> Router
    EventKnobs -. drives .-> Events
    EndingKnobs -. drives .-> Post
    PromptKnobs -. shapes every LLM call .-> LLM
    BudgetKnobs -. limits .-> LLM
```

## State ownership

| LLM call | Direct output | State it can influence | Deterministic boundary |
| --- | --- | --- | --- |
| Advisor Q&A | Advice and proposed advisor deltas | Advisor council state | `update_advisor_council()` validates and clamps deltas |
| Player compiler | `ActionPackage` candidates | All action effects indirectly | `DeterministicEngineV2` validates and resolves them |
| NPC faction turn | Perception, memory, debate, action choice | Faction beliefs, memory, unresolved questions, narrative arguments/influence; action effects indirectly | Faction output is catalog-validated; cognitive updates remain actor-local |
| International pressure | Signal candidates | Inboxes and timelines indirectly | Signal builder and info channel validate recipients/delivery |
| Event creator | Public brief and event candidate | Public timeline; scenario events indirectly | Scenario event resolver decides whether effects fire |
| Signal distortion | Observed wording | Recipient perception only | Original signal and deterministic state remain unchanged |
| Backchannel reply | Response text and bounded hints | Thread trust/leak/relationship | Code applies bounded deltas |
| Backchannel state | Beliefs, memory, unresolved question | Target actor-local state | Code applies local updates only |

## Important ordering

```mermaid
sequenceDiagram
    participant W as WorldState
    participant G as Player compiler
    participant F as NPC faction calls
    participant E as Deterministic engine
    participant R as Info channel
    participant P as Pressure rules
    participant M as Media/event call
    participant X as Scenario events
    participant U as Post-turn updates

    W->>G: visible context
    G->>F: player package is compiled, not yet resolved
    F->>W: faction perception is persisted; faction packages collected
    F->>E: player + NPC packages
    E->>R: resolved metrics, clocks, resources, signals
    R->>P: delivered observations and routed world
    P->>M: pressure rules and hidden obligations applied
    M->>X: public brief and optional event candidate
    X->>R: fired event signals are routed
    R->>U: record missing player signals as actor-local posture evidence
    U->>W: choices, advisors, threads, endings, next-turn state
```

The faction LLM sees its persisted beliefs, memory, unresolved questions, and
narrative state on the next turn. If no player signal reached it, it also sees a
local observation that the absence could mean restraint, indecision,
concealment, or weakness. The existing faction call interprets that evidence;
no extra LLM call was added. Omniscient truth metrics and hidden clocks remain
deterministic and reach factions only through visible evidence.
