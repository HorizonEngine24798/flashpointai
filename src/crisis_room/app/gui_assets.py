from __future__ import annotations

ROOM_ASSET_KEYS = [
    "rooms/start_screen",
    "rooms/control_tension_0",
    "rooms/control_tension_1",
    "rooms/control_tension_2",
    "rooms/control_tension_3",
    "rooms/control_tension_4",
    "rooms/advisors_room",
    "rooms/media_room",
]

ADVISOR_ASSET_BY_ID = {
    "state": "advisors/shadowed_state",
    "defense": "advisors/shadowed_defense",
    "intelligence": "advisors/shadowed_intelligence",
    "political": "advisors/shadowed_political",
    "legal_un": "advisors/shadowed_legal_un",
}
UNKNOWN_ADVISOR_ASSET_KEY = "advisors/shadowed_unknown"
ADVISOR_ASSET_KEYS = [
    *ADVISOR_ASSET_BY_ID.values(),
    UNKNOWN_ADVISOR_ASSET_KEY,
    "advisors/shadowed_state_female",
    "advisors/shadowed_defense_female",
    "advisors/shadowed_intelligence_female",
    "advisors/shadowed_political_female",
    "advisors/shadowed_legal_un_female",
    "advisors/shadowed_unknown_female",
]

UI_ASSET_KEYS = [
    "ui/action_button_idle",
    "ui/action_button_hover",
    "ui/action_button_pressed",
    "ui/action_button_disabled",
    "ui/ticker_static_strip",
    "ui/noise_grain",
    "ui/vignette_overlay",
    "ui/tv_static_loop_source",
]

SCENARIO_THUMBNAIL_BY_ID = {
    "cuban_missile_crisis_1962": "scenarios/cuba_missile_crisis",
}

LIGHTING_BAND_BY_TENSION = {
    0: "cold",
    1: "watchful",
    2: "amber",
    3: "red",
    4: "severe",
}


def advisor_asset_key(advisor_id: str) -> str:
    return ADVISOR_ASSET_BY_ID.get(advisor_id, UNKNOWN_ADVISOR_ASSET_KEY)


def scenario_thumbnail_key(scenario_id: str) -> str:
    return SCENARIO_THUMBNAIL_BY_ID.get(scenario_id, "scenarios/cuba_missile_crisis")


def lighting_band(tension_level: int) -> str:
    return LIGHTING_BAND_BY_TENSION.get(tension_level, "cold")
