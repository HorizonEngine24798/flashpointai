import type { CSSProperties } from "react";
import type { GameView } from "../api/types";
import { endingAssetUrl } from "../assets";

type ConclusionScreenProps = {
  view: GameView;
  onReturnToMenu: () => void;
};

export function ConclusionScreen({ view, onReturnToMenu }: ConclusionScreenProps) {
  const endingId = view.turn.accepted_ending_id;
  const title = endingId.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

  return (
    <main
      className="conclusion-screen"
      style={{ "--ending-bg": `url(${endingAssetUrl(endingId)})` } as CSSProperties}
    >
      <div className="conclusion-shade" />
      <section className="conclusion-card" aria-labelledby="conclusion-title">
        <span>Crisis concluded · Turn {view.turn.turn_number}</span>
        <h1 id="conclusion-title">{title}</h1>
        <p>{view.turn.final_summary}</p>
        <button className="menu-button primary" type="button" onClick={onReturnToMenu}>
          Return to Main Menu
        </button>
      </section>
    </main>
  );
}
