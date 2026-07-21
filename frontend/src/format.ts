import type { SaveSummaryView } from "./api/types";

export function saveLabel(save: SaveSummaryView) {
  return `${save.scenario_title || save.scenario_id} - turn ${save.turn_number}`;
}
