import type { GameView, SaveSummaryView, ScenarioOptionView } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";
const USE_MOCK_GAME_VIEW = import.meta.env.VITE_USE_MOCK_GAME_VIEW === "true";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (USE_MOCK_GAME_VIEW) {
    throw new Error("Mock GUI fixture was removed during the room UI reset.");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      const text = await response.text();
      if (text) {
        message = text;
      }
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  state: () => request<GameView>("/api/state"),
  scenarios: () => request<ScenarioOptionView[]>("/api/scenarios"),
  newSession: (scenario_id: string) =>
    request<GameView>("/api/session/new", {
      method: "POST",
      body: JSON.stringify({ scenario_id })
    }),
  continueLatest: () =>
    request<GameView>("/api/session/continue", {
      method: "POST"
    }),
  askAdvisors: (question: string) =>
    request<GameView>("/api/advisors/ask", {
      method: "POST",
      body: JSON.stringify({ question })
    }),
  previewPlan: (text: string) =>
    request<GameView>("/api/plan/preview", {
      method: "POST",
      body: JSON.stringify({ text })
    }),
  commitPlan: () =>
    request<GameView>("/api/plan/commit", {
      method: "POST"
    }),
  freeformAction: (text: string) =>
    request<GameView>("/api/action/freeform", {
      method: "POST",
      body: JSON.stringify({ text })
    }),
  selectCard: (card_id: string) =>
    request<GameView>("/api/agenda/select", {
      method: "POST",
      body: JSON.stringify({ card_id })
    }),
  removeAgendaItem: (agenda_item_id: string) =>
    request<GameView>("/api/agenda/remove", {
      method: "POST",
      body: JSON.stringify({ agenda_item_id })
    }),
  clearAgenda: () =>
    request<GameView>("/api/agenda/clear", {
      method: "POST"
    }),
  commitAgenda: () =>
    request<GameView>("/api/agenda/commit", {
      method: "POST"
    }),
  endTurn: () =>
    request<GameView>("/api/turn/end", {
      method: "POST"
    }),
  saves: () => request<SaveSummaryView[]>("/api/saves"),
  saveGame: (name: string) =>
    request<GameView>("/api/saves", {
      method: "POST",
      body: JSON.stringify({ name: name || null })
    }),
  loadSave: (save_id: string) =>
    request<GameView>("/api/saves/load", {
      method: "POST",
      body: JSON.stringify({ save_id })
    }),
  toggleDebug: (enabled: boolean | null = null) =>
    request<GameView>("/api/debug/toggle", {
      method: "POST",
      body: JSON.stringify({ enabled })
    }),
  sendBackchannel: (target_query: string, message_text: string) =>
    request<GameView>("/api/backchannels/send", {
      method: "POST",
      body: JSON.stringify({ target_query, message_text })
    }),
  acceptEnding: (query = "latest") =>
    request<GameView>("/api/endings/accept", {
      method: "POST",
      body: JSON.stringify({ query })
    }),
  rejectEnding: (query = "latest") =>
    request<GameView>("/api/endings/reject", {
      method: "POST",
      body: JSON.stringify({ query })
    })
};
