import { Play, RotateCcw, Settings } from "lucide-react";
import type { CSSProperties } from "react";
import type { SaveSummaryView, StartMenuView } from "../api/types";
import { roomAssets } from "../assets";
import { saveLabel } from "../format";

type StartScreenProps = {
  startMenu?: StartMenuView;
  fallbackSave?: SaveSummaryView | null;
  busy: string | null;
  onContinue: () => void;
  onStartNew: () => void;
  onSettings: () => void;
};

export function StartScreen({
  startMenu,
  fallbackSave,
  busy,
  onContinue,
  onStartNew,
  onSettings
}: StartScreenProps) {
  const recentSave = startMenu?.recent_save ?? fallbackSave ?? null;
  const canContinue = Boolean(startMenu?.continue_available && recentSave);

  return (
    <main
      className="start-screen"
      style={{ "--room-bg": `url(${roomAssets.start})` } as CSSProperties}
    >
      <div className="screen-shade" />
      <section className="start-menu" aria-label="Main menu">
        <div className="title-lockup">
          <h1>{startMenu?.title ?? "The Crisis Room"}</h1>
          <p>{startMenu?.subtitle ?? "where good intentions go to die"}</p>
        </div>

        <div className="menu-actions">
          <button
            className="menu-button primary"
            type="button"
            onClick={onContinue}
            disabled={!canContinue || Boolean(busy)}
          >
            <RotateCcw size={18} aria-hidden="true" />
            <span>Continue</span>
          </button>
          <button
            className="menu-button"
            type="button"
            onClick={onStartNew}
            disabled={Boolean(busy)}
          >
            <Play size={18} aria-hidden="true" />
            <span>Start New Game</span>
          </button>
          <button
            className="menu-button"
            type="button"
            onClick={onSettings}
            disabled={Boolean(busy)}
          >
            <Settings size={18} aria-hidden="true" />
            <span>Settings</span>
          </button>
        </div>

        {recentSave ? <p className="save-hint">{saveLabel(recentSave)}</p> : null}
      </section>
    </main>
  );
}
