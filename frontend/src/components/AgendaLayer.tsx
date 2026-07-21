import { ChevronDown, ChevronUp, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { AgendaConflictView, AgendaView, PlanPreviewView } from "../api/types";

type AgendaLayerProps = {
  agenda: AgendaView;
  planPreview: PlanPreviewView;
  conflicts: AgendaConflictView[];
  onRemove: (agendaItemId: string) => void;
  onClear: () => void;
  onCancelPlan: () => void;
};

export function AgendaLayer({
  agenda,
  planPreview,
  conflicts,
  onRemove,
  onClear,
  onCancelPlan
}: AgendaLayerProps) {
  const hasAgenda = agenda.items.length > 0;
  const hasPreview = Boolean(planPreview);
  const [expanded, setExpanded] = useState(true);

  return (
    <aside className={`agenda-layer ${expanded ? "expanded" : "collapsed"}`} aria-label="Agenda">
      <button
        className="agenda-toggle"
        type="button"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span>{hasPreview ? "Freeform plan" : "Card agenda"} · action slots</span>
        <b>
          {planPreview?.action_slots_used ?? agenda.items.length}/{planPreview?.action_slots_available ?? agenda.max_actions}
        </b>
        {expanded ? <ChevronDown size={17} aria-hidden="true" /> : <ChevronUp size={17} aria-hidden="true" />}
      </button>

      {expanded && conflicts.length ? (
        <div className="conflict-list">
          {conflicts.map((conflict) => (
            <p className={`conflict ${conflict.severity}`} key={conflict.conflict_id}>
              <strong>{conflict.title}</strong>
              <span>{conflict.summary}</span>
            </p>
          ))}
        </div>
      ) : null}

      {expanded && hasAgenda ? (
        <div className="agenda-items">
          {agenda.items.map((item) => (
            <article className="agenda-item" key={item.agenda_item_id}>
              <div>
                <strong>{item.title}</strong>
                <span>{item.source_title}</span>
              </div>
              <button
                className="icon-command"
                type="button"
                onClick={() => onRemove(item.agenda_item_id)}
                title="Remove"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </article>
          ))}
        </div>
      ) : null}

      {expanded && planPreview ? (
        <div className="plan-preview">
          <strong>Plan preview</strong>
          <p>{planPreview.player_intent}</p>
          <span>{planPreview.action_slots_used}/{planPreview.action_slots_available} action slots used</span>
          {planPreview.actions.length ? (
            <ul>
              {planPreview.actions.map((action) => (
                <li key={`${action.action_id}-${action.capability_id ?? "base"}`}>
                  <strong>{action.title}</strong>
                  {action.intent_summary ? ` — ${action.intent_summary}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {[...planPreview.errors, ...planPreview.warnings].map((message) => (
            <span className="warning-line" key={message}>
              {message}
            </span>
          ))}
          <PlanDetails title="Compiled intents" items={planPreview.compiled_intents} />
          <PlanDetails title="Rejected intents" items={planPreview.rejected_intents} />
          <PlanDetails title="Unprocessed intents" items={planPreview.unprocessed_intents} />
          <PlanDetails title="Known pending actions" items={planPreview.known_pending_actions} />
          <PlanDetails title="Resource pressure" items={planPreview.resource_pressure} />
          <PlanDetails title="Backchannel constraints" items={planPreview.open_backchannel_constraints} />
          <PlanDetails title="Recent event context" items={planPreview.recent_event_context} />
          <PlanDetails title="Flash-event risks" items={planPreview.visible_flash_event_risks} />
          <PlanDetails title="Known consequences and risks" items={planPreview.known_consequences} />
          <PlanDetails title="Why this plan" items={planPreview.notes} />
        </div>
      ) : null}

      {expanded && !hasAgenda && !hasPreview ? (
        <p className="empty-copy">No actions selected. Choose a proposal or write a plan.</p>
      ) : null}

      {expanded && (hasAgenda || hasPreview) ? (
        <button className="clear-agenda" type="button" onClick={hasPreview ? onCancelPlan : onClear}>
          <Trash2 size={15} aria-hidden="true" />
          <span>{hasPreview ? "Cancel freeform plan" : "Clear card agenda"}</span>
        </button>
      ) : null}
    </aside>
  );
}

function PlanDetails({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return <details><summary>{title}</summary><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></details>;
}
