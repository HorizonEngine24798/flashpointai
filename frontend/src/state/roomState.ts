export type RoomId = "control" | "advisors" | "media";

export type OverlayId = "debug" | "settings" | null;

export type AppScreen = "start_menu" | "scenario_select" | "game";

export const roomLabels: Record<RoomId, string> = {
  control: "Control Room",
  advisors: "Advisors Room",
  media: "Media and Channels"
};
