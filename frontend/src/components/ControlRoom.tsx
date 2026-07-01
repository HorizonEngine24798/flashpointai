import type { CSSProperties } from "react";
import type { GameView } from "../api/types";
import { assetUrl } from "../assets";
import { ActionButton } from "./ActionButton";
import { AgendaLayer } from "./AgendaLayer";
import { SlideRail } from "./SlideRail";

type ControlRoomProps = {
  view: GameView;
  busy: string | null;
  actionLabel: string;
  actionBlockedReason: string;
  actionDisabled: boolean;
  onResolve: () => void;
  onRemoveAgenda: (agendaItemId: string) => void;
  onClearAgenda: () => void;
};

export function ControlRoom({
  view,
  busy,
  actionLabel,
  actionBlockedReason,
  actionDisabled,
  onResolve,
  onRemoveAgenda,
  onClearAgenda
}: ControlRoomProps) {
  const room = view.control_room;

  return (
    <section
      className={`room room-control lighting-${view.scene.lighting_band}`}
      style={{ "--room-bg": `url(${assetUrl(view.scene.room_asset_key)})` } as CSSProperties}
    >
      <SlideRail side="left" title="Results">
        {room.recent_results.length ? (
          room.recent_results.map((line) => <p key={line}>{line}</p>)
        ) : (
          <p className="empty-copy">No turn results yet.</p>
        )}
      </SlideRail>

      <div className="control-center">
        <span className="turn-chip">
          Turn {view.turn.turn_number}
          {view.turn.time_label ? ` - ${view.turn.time_label}` : ""}
        </span>
        <h2>{view.scenario.title}</h2>
        <p className="situation-summary">{room.situation_summary}</p>

        <div className="problem-stack" aria-label="Open problems">
          {room.open_problems.map((problem) => (
            <article className={`problem-card urgency-${problem.urgency}`} key={problem.problem_id}>
              <span>{problem.urgency}</span>
              <strong>{problem.title}</strong>
              <p>{problem.summary}</p>
            </article>
          ))}
          {!room.open_problems.length ? <p className="empty-copy">No open problems.</p> : null}
        </div>
      </div>

      <AgendaLayer
        agenda={room.agenda}
        planPreview={view.plan_preview}
        conflicts={room.agenda_conflicts}
        onRemove={onRemoveAgenda}
        onClear={onClearAgenda}
      />

      <SlideRail side="right" title="Pressure">
        <div className="pressure-stack">
          {room.pressure.map((pressure) => (
            <article className={`pressure-row band-${pressure.band}`} key={pressure.key}>
              <header>
                <strong>{pressure.label}</strong>
                <span>{pressure.band}</span>
              </header>
              <p>{pressure.visible_summary}</p>
              <div className="pressure-track">
                <span />
              </div>
            </article>
          ))}
        </div>
        <div className="resource-stack">
          {room.resources.map((resource) => (
            <article className="resource-row" key={resource.key}>
              <strong>{resource.label}</strong>
              <b>{resource.value}</b>
              {resource.note ? <span>{resource.note}</span> : null}
            </article>
          ))}
        </div>
      </SlideRail>

      <ActionButton
        label={actionLabel}
        blockedReason={actionBlockedReason}
        busy={busy}
        disabled={actionDisabled}
        onAction={onResolve}
      />
    </section>
  );
}
