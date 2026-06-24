# Cleanup Ledger

Last updated: 2026-06-24

This ledger tracks large modules that should be split or reduced only when a
feature phase is already touching their behavior. Avoid broad formatting or
layout-only churn before the capability migration changes the action interfaces.

## Current Large Modules

| Lines | Module | Follow-up |
| ---: | --- | --- |
| 1132 | `src/crisis_room/scenario/schema.py` | Split as part of the capability migration into scenario entities, capabilities, events, and advisor seeds if the migration needs it. |
| 902 | `src/crisis_room/app/presentation.py` | Reduce when action card, plan preview, and debug visibility rendering changes are made. |
| 706 | `src/crisis_room/engine/adjudication.py` | Revisit while replacing scenario-specific action handling with resolved capabilities. |
| 676 | `src/crisis_room/app/advisor_updates.py` | Revisit during the advisor council contract work, especially around state deltas and visibility. |
| 656 | `src/crisis_room/llm/scripted_client.py` | Reduce while updating scripted outputs for generic actions and strict capabilities. |
| 566 | `src/crisis_room/app/tui.py` | Revisit when normal/debug advisor visibility and save flows are changed. |
| 544 | `src/crisis_room/app/backchannels.py` | Reduce during the capability-owned backchannel upgrade. |

## Gate

For each later phase, run the supported conda pytest command before and after
the phase. If a touched module remains above roughly 500 lines, either reduce it
in that phase or leave a brief reason in this ledger.
