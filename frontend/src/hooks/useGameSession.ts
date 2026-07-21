import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { GameView, ScenarioOptionView } from "../api/types";

export function useGameSession() {
  const [view, setView] = useState<GameView | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioOptionView[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function run(label: string, operation: () => Promise<GameView>) {
    setBusy(label);
    setError("");
    try {
      const next = await operation();
      setView(next);
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    run("Loading state", api.state);
    api
      .scenarios()
      .then(setScenarios)
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      });
  }, []);

  return {
    view,
    scenarios,
    busy,
    error,
    setError,
    startNewGame: (scenarioId: string) =>
      run("Starting scenario", () => api.newSession(scenarioId)),
    continueLatest: () => run("Loading save", api.continueLatest),
    askAdvisors: (question: string) => run("Asking council", () => api.askAdvisors(question)),
    previewPlan: (text: string) => run("Previewing plan", () => api.previewPlan(text)),
    commitPlan: () => run("Committing plan", api.commitPlan),
    cancelPlan: () => run("Cancelling plan", api.cancelPlan),
    selectCard: (cardId: string) => run("Adding card", () => api.selectCard(cardId)),
    removeAgendaItem: (agendaItemId: string) =>
      run("Removing item", () => api.removeAgendaItem(agendaItemId)),
    clearAgenda: () => run("Clearing agenda", api.clearAgenda),
    commitAgenda: () => run("Resolving agenda", api.commitAgenda),
    endTurn: () => run("Holding position", api.endTurn),
    saveGame: (name: string) => run("Saving", () => api.saveGame(name)),
    loadSave: (saveId: string) => run("Loading save", () => api.loadSave(saveId)),
    sendBackchannel: (target: string, message: string) =>
      run("Sending backchannel", () => api.sendBackchannel(target, message)),
    acceptEnding: () => run("Accepting ending", () => api.acceptEnding()),
    rejectEnding: () => run("Rejecting ending", () => api.rejectEnding())
  };
}
