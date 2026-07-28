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
  onCancelPlan: () => void;
};

export function ControlRoom({
  view,
  busy,
  actionLabel,
  actionBlockedReason,
  actionDisabled,
  onResolve,
  onRemoveAgenda,
  onClearAgenda,
  onCancelPlan
}: ControlRoomProps) {
  const room = view.control_room;

  return (
    <section
      className={`room room-control lighting-${view.scene.lighting_band}`}
      style={{ "--room-bg": `url(${assetUrl(view.scene.room_asset_key)})` } as CSSProperties}
    >
      <SlideRail
        side="left"
        title="Results"
        attentionKey={room.latest_result ? `${room.latest_result.turn_number}:${room.latest_result.rendered_text}` : undefined}
      >
        {room.latest_result ? (
          <div className="result-drawer">
            <strong>Turn {room.latest_result.turn_number} report</strong>
            <ResultSection title="Critical warnings" items={room.latest_result.critical_warnings} warning />
            <ResultSection title="Resolved" items={room.latest_result.resolved_actions} />
            <ResultSection title="Accepted" items={room.latest_result.accepted_actions} />
            <ResultSection title="Scheduled" items={room.latest_result.scheduled_actions} />
            <ResultSection title="Decision impact" items={room.latest_result.action_results} />
            <ResultSection title="Chief of Staff" items={room.latest_result.chief_updates} />
            <ResultSection title="Blocked by resources" items={room.latest_result.resource_blocked_actions} warning />
            <ResultSection title="Rejected" items={room.latest_result.rejected_actions} warning />
            <ResultSection title="Internal pressure" items={room.latest_result.pressure_updates} />
            <ResultSection title="Consequences" items={room.latest_result.consequences} />
            <ResultSection title="Events" items={room.latest_result.flash_events} />
            <ResultSection title="Media" items={room.latest_result.media_headlines} />
            <ResultSection title="Council reaction" items={room.latest_result.advisor_reactions} />
            <ResultSection title="Other reactions" items={room.latest_result.npc_reactions} />
            <ResultSection title="Agenda warnings" items={room.latest_result.batch_warnings} warning />
            {room.latest_result.rendered_text ? (
              <details>
                <summary>Full report</summary>
                <pre>{room.latest_result.rendered_text}</pre>
              </details>
            ) : null}
          </div>
        ) : room.recent_results.length ? (
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

        {room.critical_warnings.length ? (
          <aside className="critical-banner" aria-label="Critical warnings">
            <strong>Critical warnings</strong>
            {room.critical_warnings.map((warning) => <p key={warning}>{warning}</p>)}
          </aside>
        ) : null}

        {room.chief_plan ? (
          <aside className="chief-plan" aria-label="Chief of Staff plan">
            <header>
              <strong>Chief of Staff plan</strong>
              <span>Advisory</span>
            </header>
            {room.chief_plan.objectives.map((objective) => <p key={objective}>{objective}</p>)}
            {room.chief_plan.recommended_actions.length ? (
              <small>Recommended: {room.chief_plan.recommended_actions.join(" · ")}</small>
            ) : null}
            {room.chief_plan.latest_assessment ? (
              <small>{room.chief_plan.latest_assessment}</small>
            ) : null}
          </aside>
        ) : null}

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
        onCancelPlan={onCancelPlan}
      />

      <SlideRail side="right" title="Crisis pressure">
        <div className="pressure-stack">
          {room.pressure.map((pressure) => (
            <article className={`pressure-row band-${pressure.band}`} key={pressure.key}>
              <header>
                <strong>{pressure.label}</strong>
                <span>{pressure.band} · {pressure.trend}</span>
              </header>
              <p>{pressure.visible_summary}</p>
              <small>Confidence: {pressure.confidence}. Qualitative reading.</small>
            </article>
          ))}
        </div>
        <h3 className="rail-subheading">Presidential resources</h3>
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

function ResultSection({ title, items, warning = false }: { title: string; items: string[]; warning?: boolean }) {
  if (!items.length) return null;
  return (
    <section className={warning ? "result-section warning-line" : "result-section"}>
      <strong>{title}</strong>
      {items.map((item) => <p key={item}>{item}</p>)}
    </section>
  );
}
