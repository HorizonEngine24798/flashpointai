import startScreen from "./assets/rooms/start_screen.png";
import controlTension0 from "./assets/rooms/control_tension_0.png";
import controlTension1 from "./assets/rooms/control_tension_1.png";
import controlTension2 from "./assets/rooms/control_tension_2.png";
import controlTension3 from "./assets/rooms/control_tension_3.png";
import controlTension4 from "./assets/rooms/control_tension_4.png";
import advisorsRoom from "./assets/rooms/advisors_room.png";
import mediaRoom from "./assets/rooms/media_room.png";
import cubaScenario from "./assets/scenarios/cuba_missile_crisis.png";
import endingEscalation from "./assets/endings/escalation.png";
import endingFailedControl from "./assets/endings/failed_control.png";
import endingSettlement from "./assets/endings/settlement.png";
import shadowedState from "./assets/advisors/shadowed_state.png";
import shadowedDefense from "./assets/advisors/shadowed_defense.png";
import shadowedIntelligence from "./assets/advisors/shadowed_intelligence.png";
import shadowedPolitical from "./assets/advisors/shadowed_political.png";
import shadowedLegalUn from "./assets/advisors/shadowed_legal_un.png";
import shadowedUnknown from "./assets/advisors/shadowed_unknown.png";
import shadowedStateFemale from "./assets/advisors/shadowed_state_female.png";
import shadowedDefenseFemale from "./assets/advisors/shadowed_defense_female.png";
import shadowedIntelligenceFemale from "./assets/advisors/shadowed_intelligence_female.png";
import shadowedPoliticalFemale from "./assets/advisors/shadowed_political_female.png";
import shadowedLegalUnFemale from "./assets/advisors/shadowed_legal_un_female.png";
import shadowedUnknownFemale from "./assets/advisors/shadowed_unknown_female.png";
import actionButtonIdle from "./assets/ui/action_button_idle.png";
import actionButtonHover from "./assets/ui/action_button_hover.png";
import actionButtonPressed from "./assets/ui/action_button_pressed.png";
import actionButtonDisabled from "./assets/ui/action_button_disabled.png";
import tickerStaticStrip from "./assets/ui/ticker_static_strip.png";
import tvStaticSource from "./assets/ui/tv_static_loop_source.png";

const advisorVariantAssets = {
  state: {
    male: shadowedState,
    female: shadowedStateFemale
  },
  defense: {
    male: shadowedDefense,
    female: shadowedDefenseFemale
  },
  intelligence: {
    male: shadowedIntelligence,
    female: shadowedIntelligenceFemale
  },
  political: {
    male: shadowedPolitical,
    female: shadowedPoliticalFemale
  },
  legal_un: {
    male: shadowedLegalUn,
    female: shadowedLegalUnFemale
  },
  unknown: {
    male: shadowedUnknown,
    female: shadowedUnknownFemale
  }
} as const;

type AdvisorRole = keyof typeof advisorVariantAssets;
type AdvisorVariant = keyof (typeof advisorVariantAssets)[AdvisorRole];

const advisorAssetAliases: Record<string, AdvisorRole> = {
  "advisors/shadowed_state": "state",
  "advisors/shadowed_defense": "defense",
  "advisors/shadowed_intelligence": "intelligence",
  "advisors/shadowed_political": "political",
  "advisors/shadowed_legal_un": "legal_un",
  "advisors/shadowed_unknown": "unknown"
};

const sessionAdvisorVariants: Record<AdvisorRole, AdvisorVariant> = {
  state: randomAdvisorVariant(),
  defense: randomAdvisorVariant(),
  intelligence: randomAdvisorVariant(),
  political: randomAdvisorVariant(),
  legal_un: randomAdvisorVariant(),
  unknown: randomAdvisorVariant()
};

function randomAdvisorVariant(): AdvisorVariant {
  return Math.random() < 0.5 ? "male" : "female";
}

function advisorAssetUrl(key: string) {
  const role = advisorAssetAliases[key];
  if (!role) {
    return null;
  }
  return advisorVariantAssets[role][sessionAdvisorVariants[role]];
}

const assets: Record<string, string> = {
  "rooms/start_screen": startScreen,
  "rooms/control_tension_0": controlTension0,
  "rooms/control_tension_1": controlTension1,
  "rooms/control_tension_2": controlTension2,
  "rooms/control_tension_3": controlTension3,
  "rooms/control_tension_4": controlTension4,
  "rooms/advisors_room": advisorsRoom,
  "rooms/media_room": mediaRoom,
  "scenarios/cuba_missile_crisis": cubaScenario,
  "advisors/shadowed_state_female": shadowedStateFemale,
  "advisors/shadowed_defense_female": shadowedDefenseFemale,
  "advisors/shadowed_intelligence_female": shadowedIntelligenceFemale,
  "advisors/shadowed_political_female": shadowedPoliticalFemale,
  "advisors/shadowed_legal_un_female": shadowedLegalUnFemale,
  "advisors/shadowed_unknown_female": shadowedUnknownFemale,
  "ui/action_button_idle": actionButtonIdle,
  "ui/action_button_hover": actionButtonHover,
  "ui/action_button_pressed": actionButtonPressed,
  "ui/action_button_disabled": actionButtonDisabled,
  "ui/ticker_static_strip": tickerStaticStrip,
  "ui/tv_static_loop_source": tvStaticSource
};

export function assetUrl(key: string, fallback = "rooms/control_tension_0") {
  const advisorUrl = advisorAssetUrl(key);
  if (advisorUrl) {
    return advisorUrl;
  }
  return assets[key] ?? advisorAssetUrl(fallback) ?? assets[fallback] ?? "";
}

export function endingAssetUrl(endingId: string) {
  if (endingId === "settlement_reached") return endingSettlement;
  if (endingId === "nuclear_exchange") return endingEscalation;
  return endingFailedControl;
}

export const roomAssets = {
  start: startScreen,
  advisors: advisorsRoom,
  media: mediaRoom,
  ticker: tickerStaticStrip,
  static: tvStaticSource,
  actionIdle: actionButtonIdle,
  actionHover: actionButtonHover,
  actionPressed: actionButtonPressed,
  actionDisabled: actionButtonDisabled
};
