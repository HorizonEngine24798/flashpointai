import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { DebugOverlay } from "./components/DebugOverlay";
import { ConclusionScreen } from "./components/ConclusionScreen";
import { GameShell } from "./components/GameShell";
import { ScenarioSelect } from "./components/ScenarioSelect";
import { SettingsOverlay } from "./components/SettingsOverlay";
import { StartScreen } from "./components/StartScreen";
import { useGameSession } from "./hooks/useGameSession";
import type { AppScreen, OverlayId, RoomId } from "./state/roomState";

export function App() {
  const session = useGameSession();
  const [screen, setScreen] = useState<AppScreen>("start_menu");
  const [room, setRoom] = useState<RoomId>("control");
  const [overlay, setOverlay] = useState<OverlayId>(null);

  const recentSave = useMemo(
    () => session.view?.saves.find((save) => save.compatible) ?? null,
    [session.view?.saves]
  );

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") {
        return;
      }
      if (overlay) {
        setOverlay(null);
        return;
      }
      if (screen === "scenario_select") {
        setScreen("start_menu");
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [overlay, screen]);

  async function startScenario(scenarioId: string) {
    const next = await session.startNewGame(scenarioId);
    if (next) {
      setRoom("control");
      setScreen("game");
    }
  }

  async function continueLatest() {
    const next = await session.continueLatest();
    if (next) {
      setRoom("control");
      setScreen("game");
    }
  }

  function exitToStart() {
    setOverlay(null);
    setScreen("start_menu");
  }

  return (
    <>
      {screen === "start_menu" ? (
        <StartScreen
          startMenu={session.view?.start_menu}
          fallbackSave={recentSave}
          busy={session.busy}
          onContinue={continueLatest}
          onStartNew={() => setScreen("scenario_select")}
          onSettings={() => setOverlay("settings")}
        />
      ) : null}

      {screen === "scenario_select" ? (
        <ScenarioSelect
          scenarios={session.scenarios.length ? session.scenarios : session.view?.scenario_options ?? []}
          busy={session.busy}
          onBack={() => setScreen("start_menu")}
          onStart={startScenario}
        />
      ) : null}

      {screen === "game" && session.view?.turn.is_concluded ? (
        <ConclusionScreen view={session.view} onReturnToMenu={exitToStart} />
      ) : null}

      {screen === "game" && session.view && !session.view.turn.is_concluded ? (
        <GameShell
          view={session.view}
          busy={session.busy}
          room={room}
          onRoomChange={setRoom}
          onOpenDebug={() => setOverlay("debug")}
          onOpenSettings={() => setOverlay("settings")}
          askAdvisors={session.askAdvisors}
          previewPlan={session.previewPlan}
          commitPlan={session.commitPlan}
          cancelPlan={session.cancelPlan}
          selectCard={session.selectCard}
          removeAgendaItem={session.removeAgendaItem}
          clearAgenda={session.clearAgenda}
          commitAgenda={session.commitAgenda}
          endTurn={session.endTurn}
          sendBackchannel={session.sendBackchannel}
          acceptEnding={session.acceptEnding}
          rejectEnding={session.rejectEnding}
        />
      ) : null}

      {overlay === "debug" && session.view ? (
        <DebugOverlay view={session.view} onClose={() => setOverlay(null)} />
      ) : null}

      {overlay === "settings" ? (
        <SettingsOverlay
          view={session.view}
          busy={session.busy}
          onClose={() => setOverlay(null)}
          onSave={session.saveGame}
          onLoad={session.loadSave}
          onExit={exitToStart}
        />
      ) : null}

      {session.error ? (
        <aside className="toast error-toast" role="alert">
          <span>{session.error}</span>
          <button className="icon-command" type="button" onClick={() => session.setError("")}>
            <X size={16} aria-hidden="true" />
          </button>
        </aside>
      ) : null}

      {session.busy ? <div className="busy-chip">{session.busy}</div> : null}
    </>
  );
}
