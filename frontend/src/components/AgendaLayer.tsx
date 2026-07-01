import { ChevronDown, ChevronUp, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { AgendaConflictView, AgendaView, PlanPreviewView } from "../api/types";

type AgendaLayerProps = {
  agenda: AgendaView;
  planPreview: PlanPreviewView;
  conflicts: AgendaConflictView[];
  onRemove: (agendaItemId: string) => void;
  onClear: () => void;
};

export function AgendaLayer({
  agenda,
  planPreview,
  conflicts,
  onRemove,
  onClear
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
        <span>Agenda</span>
        <b>
          {agenda.items.length}/{agenda.max_actions}
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
          <strong>Freeform Order</strong>
          <p>{planPreview.player_intent}</p>
          {planPreview.actions.length ? (
            <ul>
              {planPreview.actions.map((action) => (
                <li key={`${action.action_id}-${action.capability_id ?? "base"}`}>
                  {action.title}
                </li>
              ))}
            </ul>
          ) : null}
          {[...planPreview.errors, ...planPreview.warnings].map((message) => (
            <span className="warning-line" key={message}>
              {message}
            </span>
          ))}
        </div>
      ) : null}

      {expanded && !hasAgenda && !hasPreview ? <p className="empty-copy">No actions queued.</p> : null}

      {expanded && hasAgenda ? (
        <button className="clear-agenda" type="button" onClick={onClear}>
          <Trash2 size={15} aria-hidden="true" />
          <span>Clear</span>
        </button>
      ) : null}
    </aside>
  );
}
