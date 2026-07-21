import { Eye, MessageSquare, Plus, Send } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import type { ActionCardView, AdvisorProposalView, GameView } from "../api/types";
import { assetUrl, roomAssets } from "../assets";
import { AgendaLayer } from "./AgendaLayer";
import { Overlay } from "./Overlay";

type AdvisorsRoomProps = {
  view: GameView;
  busy: string | null;
  onAsk: (question: string) => void;
  onOrder: (text: string) => void;
  onSelectCard: (cardId: string) => void;
  onRemoveAgenda: (agendaItemId: string) => void;
  onClearAgenda: () => void;
  onCancelPlan: () => void;
};

type InputMode = "ask" | "plan";

export function AdvisorsRoom({
  view,
  busy,
  onAsk,
  onOrder,
  onSelectCard,
  onRemoveAgenda,
  onClearAgenda,
  onCancelPlan
}: AdvisorsRoomProps) {
  const [selectedAdvisor, setSelectedAdvisor] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [text, setText] = useState("");
  const [inputMode, setInputMode] = useState<InputMode>("ask");
  const room = view.advisor_room;
  const selectedProposal = useMemo(
    () => room.proposals.find((proposal) => proposal.advisor_id === selectedAdvisor) ?? null,
    [room.proposals, selectedAdvisor]
  );
  const selectedFigure = room.figures.find((figure) => figure.advisor_id === selectedAdvisor);
  const proposalsToShow = showAll ? room.proposals : selectedProposal ? [selectedProposal] : [];
  const overlayOpen = showAll || Boolean(selectedFigure);
  const queuedCardIds = useMemo(
    () => new Set(room.agenda.items.map((item) => item.card_id)),
    [room.agenda.items]
  );

  function submitText(onSubmit: (value: string) => void) {
    const value = text.trim();
    if (!value) {
      return;
    }
    onSubmit(value);
    setText("");
  }

  function submitCurrentMode() {
    if (
      inputMode === "plan" &&
      room.agenda.items.length &&
      !window.confirm("Draft this freeform plan and discard the current card agenda?")
    ) {
      return;
    }
    submitText(inputMode === "ask" ? onAsk : onOrder);
  }

  function queueCard(cardId: string) {
    if (queuedCardIds.has(cardId)) return;
    if (
      view.plan_preview &&
      !window.confirm("Queue this card and discard the current freeform plan?")
    ) {
      return;
    }
    onSelectCard(cardId);
  }

  return (
    <section
      className="room room-advisors"
      style={{ "--room-bg": `url(${roomAssets.advisors})` } as CSSProperties}
    >
      <details className="council-strip">
        <summary>Council Messages</summary>
        <div>
          {room.council_messages.length ? (
            room.council_messages.map((message) => <p key={message}>{message}</p>)
          ) : (
            <p className="empty-copy">No council update yet. Ask the council for a read.</p>
          )}
          {room.council_read.length ? (
            <div className="council-read">
              <strong>Current council read</strong>
              {room.council_read.map((item) => <p key={item}>{item}</p>)}
            </div>
          ) : null}
          {room.latest_dialogue ? (
            <article className="dialogue-readout">
              <strong>{room.latest_dialogue.question}</strong>
              <p>{room.latest_dialogue.answer}</p>
              {room.latest_dialogue.council_summary ? (
                <p>Council: {room.latest_dialogue.council_summary}</p>
              ) : null}
              {room.latest_dialogue.advisor_views.map((advisorView) => (
                <p key={advisorView}>{advisorView}</p>
              ))}
              {room.latest_dialogue.risk_warnings.map((warning) => (
                <p className="warning-line" key={warning}>Risk: {warning}</p>
              ))}
              {room.latest_dialogue.information_gaps.map((gap) => (
                <p key={gap}>Unknown: {gap}</p>
              ))}
              {room.latest_dialogue.visible_context_limits.map((limit) => (
                <p key={limit}>Context limit: {limit}</p>
              ))}
              {room.latest_dialogue.suggested_moves.length ? (
                <p>Suggested moves: {room.latest_dialogue.suggested_moves.map(humanizeId).join(", ")}</p>
              ) : null}
            </article>
          ) : null}
          {view.pending_event_choices.map((choice) => (
            <article className="event-choice" key={choice.choice_id}>
              <strong>Pending choice: {choice.title}</strong>
              <p>{choice.prompt}</p>
              <span>
                Expires {choice.expires_turn ? `turn ${choice.expires_turn}` : "when resolved"}.
              </span>
              <ul>
                {choice.options.map((option) => {
                  const queued = queuedCardIds.has(option.card_id);
                  return (
                    <li key={option.option_id}>
                      <span><strong>{option.label}</strong> — {option.summary}; {option.consumes_normal_action_budget ? "uses an action slot" : "event-only"}</span>
                      <button
                        className="compact-command primary"
                        type="button"
                        onClick={() => queueCard(option.card_id)}
                        disabled={queued || Boolean(busy)}
                      >
                        <Plus size={15} aria-hidden="true" />
                        <span>{queued ? "Queued" : "Queue"}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </article>
          ))}
        </div>
      </details>

      <button className="show-proposals" type="button" onClick={() => setShowAll(true)}>
        <Eye size={16} aria-hidden="true" />
        <span>Show All Proposals</span>
      </button>

      <div className="advisor-figures" aria-label="Advisors">
        {room.figures.map((figure) => (
          <button
            className={`advisor-figure ${figure.side} slot-${figure.slot} ${
              figure.has_proposals ? "has-proposals" : ""
            } ${selectedAdvisor === figure.advisor_id ? "selected" : ""}`}
            type="button"
            key={figure.advisor_id}
            onClick={() => {
              setShowAll(false);
              setSelectedAdvisor(figure.advisor_id);
            }}
          >
            <img src={assetUrl(figure.asset_key, "advisors/shadowed_unknown")} alt="" />
            <span>{figure.name}</span>
          </button>
        ))}
      </div>

      <AgendaLayer
        agenda={room.agenda}
        planPreview={view.plan_preview}
        conflicts={room.agenda_conflicts}
        onRemove={onRemoveAgenda}
        onClear={onClearAgenda}
        onCancelPlan={onCancelPlan}
      />

      {overlayOpen ? (
        <Overlay
          eyebrow={showAll ? "Council" : selectedFigure?.portfolio ?? "Advisor"}
          title={showAll ? "All Proposals" : selectedFigure?.name ?? "Advisor Proposals"}
          className="advisor-proposal-overlay"
          onClose={() => {
            setSelectedAdvisor(null);
            setShowAll(false);
          }}
        >
          {selectedFigure && !showAll ? (
            <div className="advisor-state-read">
              <span>Trust: {selectedFigure.trust}</span>
              <span>Urgency: {selectedFigure.urgency}</span>
              <span>Advisor concern: {selectedFigure.caution}</span>
              {selectedFigure.current_belief ? <p>{selectedFigure.current_belief}</p> : null}
              {selectedFigure.latest_recommendation ? (
                <p><strong>Latest recommendation:</strong> {selectedFigure.latest_recommendation}</p>
              ) : null}
              {selectedFigure.latest_concern ? <p>{selectedFigure.latest_concern}</p> : null}
            </div>
          ) : null}

          {proposalsToShow.map((proposal) => (
            <ProposalBlock
              proposal={proposal}
              busy={busy}
              queuedCardIds={queuedCardIds}
              onSelectCard={queueCard}
              key={proposal.advisor_id}
            />
          ))}
          {!proposalsToShow.length ? (
            <p className="empty-copy">
              {showAll ? "No advisor proposals available." : "No proposal available."}
            </p>
          ) : null}
        </Overlay>
      ) : null}

      <form
        className="advisor-input"
        onSubmit={(event) => {
          event.preventDefault();
          submitCurrentMode();
        }}
      >
        <div className="advisor-input-main">
          <div className="advisor-input-modes" role="tablist" aria-label="Council input mode">
            <button
              type="button"
              className={`compact-command ${inputMode === "ask" ? "primary" : ""}`}
              onClick={() => setInputMode("ask")}
              aria-pressed={inputMode === "ask"}
            >
              <MessageSquare size={16} aria-hidden="true" />
              <span>Ask council</span>
            </button>
            <button
              type="button"
              className={`compact-command ${inputMode === "plan" ? "primary" : ""}`}
              onClick={() => setInputMode("plan")}
              aria-pressed={inputMode === "plan"}
            >
              <Send size={16} aria-hidden="true" />
              <span>Draft freeform plan</span>
            </button>
          </div>
          <label>
            <span className="input-help">
              {inputMode === "ask"
                ? "Ask for advice without advancing the turn."
                : "Compile your own action plan for review before committing it."}
            </span>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder={inputMode === "ask" ? "What should the council assess?" : "Describe the actions you want to take"}
              rows={2}
            />
          </label>
        </div>
        <div className="advisor-input-actions">
          <button
            type="submit"
            className="compact-command primary"
            disabled={Boolean(busy) || !text.trim()}
          >
            {inputMode === "ask" ? <MessageSquare size={16} aria-hidden="true" /> : <Send size={16} aria-hidden="true" />}
            <span>{inputMode === "ask" ? "Ask" : "Preview plan"}</span>
          </button>
        </div>
      </form>
    </section>
  );
}

function ProposalBlock({
  proposal,
  busy,
  queuedCardIds,
  onSelectCard
}: {
  proposal: AdvisorProposalView;
  busy: string | null;
  queuedCardIds: Set<string>;
  onSelectCard: (cardId: string) => void;
}) {
  return (
    <div className="proposal-block">
      <h3>{proposal.advisor_name}</h3>
      {proposal.cards.length ? (
        proposal.cards.map((card) => (
          <ActionProposalCard
            card={card}
            busy={busy}
            queued={queuedCardIds.has(card.card_id)}
            onSelectCard={onSelectCard}
            key={card.card_id}
          />
        ))
      ) : (
        <p className="empty-copy">No proposal available.</p>
      )}
    </div>
  );
}

function ActionProposalCard({
  card,
  busy,
  queued,
  onSelectCard
}: {
  card: ActionCardView;
  busy: string | null;
  queued: boolean;
  onSelectCard: (cardId: string) => void;
}) {
  return (
    <button
      className={`proposal-card urgency-${card.urgency}`}
      type="button"
      onClick={() => onSelectCard(card.card_id)}
      disabled={!card.legal_now || queued || Boolean(busy)}
    >
      <div>
        <strong>{card.title}</strong>
        {card.prompt_hint ? <p><b>Context:</b> {card.prompt_hint}</p> : null}
        {card.cost_summary ? <p><b>Cost:</b> {card.cost_summary}</p> : null}
        {card.expected_pressure_summary ? <p><b>Likely effect:</b> {card.expected_pressure_summary}</p> : null}
        {card.risk_summary ? <p><b>Risk:</b> {card.risk_summary}</p> : null}
        <span>{card.category} · {card.legal_now ? "available" : "unavailable"}</span>
        {!card.legal_now && card.locked_reason ? (
          <span className="warning-line">{card.locked_reason}</span>
        ) : null}
      </div>
      <span className="proposal-queue">
        <Plus size={15} aria-hidden="true" />
        <b>{queued ? "Queued" : "Queue"}</b>
      </span>
    </button>
  );
}

function humanizeId(value: string) {
  return value.replace(/[_-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
