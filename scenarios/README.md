# Scenarios

The built-in `cuban_missile_crisis_1962` scenario is assembled from the
focused modules in `src/crisis_room/scenario/` and loaded by default.

The launcher also accepts a complete `Scenario` JSON document:

```powershell
python main.py --scenario path/to/scenario.json
python main.py --scenario my_scenario --scenario-dir path/to/scenarios
```

External scenarios are validated at launch for stable IDs, duplicate IDs, and
broken entity, action, capability, event, and ending references. The canonical
schema is the `Scenario` model in `src/crisis_room/scenario/schema.py`.
