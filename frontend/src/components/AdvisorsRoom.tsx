import { Eye, MessageSquare, Plus, Send, X } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import type { ActionCardView, AdvisorProposalView, GameView } from "../api/types";
import { assetUrl, roomAssets } from "../assets";
import { AgendaLayer } from "./AgendaLayer";

type AdvisorsRoomProps = {
  view: GameView;
  busy: string | null;
  onAsk: (question: string) => void;
  onOrder: (text: string) => void;
  onSelectCard: (cardId: string) => void;
  onRemoveAgenda: (agendaItemId: string) => void;
  onClearAgenda: () => void;
};

export function AdvisorsRoom({
  view,
  busy,
  onAsk,
  onOrder,
  onSelectCard,
  onRemoveAgenda,
  onClearAgenda
}: AdvisorsRoomProps) {
  const [selectedAdvisor, setSelectedAdvisor] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [text, setText] = useState("");
  const room = view.advisor_room;
  const selectedProposal = useMemo(
    () => room.proposals.find((proposal) => proposal.advisor_id === selectedAdvisor) ?? null,
    [room.proposals, selectedAdvisor]
  );
  const selectedFigure = room.figures.find((figure) => figure.advisor_id === selectedAdvisor);
  const proposalsToShow = showAll ? room.proposals : selectedProposal ? [selectedProposal] : [];
  const overlayOpen = showAll || Boolean(selectedFigure);

  function submitAsk() {
    const value = text.trim();
    if (!value) {
      return;
    }
    onAsk(value);
    setText("");
  }

  function submitOrder() {
    const value = text.trim();
    if (!value) {
      return;
    }
    onOrder(value);
    setText("");
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
            <p className="empty-copy">No council update.</p>
          )}
          {room.latest_dialogue ? (
            <article className="dialogue-readout">
              <strong>{room.latest_dialogue.question}</strong>
              <p>{room.latest_dialogue.answer}</p>
            </article>
          ) : null}
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
      />

      {overlayOpen ? (
        <div
          className="advisor-overlay-backdrop"
          role="presentation"
          onClick={() => {
            setSelectedAdvisor(null);
            setShowAll(false);
          }}
        >
          <section
            className="advisor-proposal-overlay"
            aria-label="Advisor proposals"
            onClick={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <span>{showAll ? "Council" : selectedFigure?.portfolio}</span>
                <h2>{showAll ? "All Proposals" : selectedFigure?.name}</h2>
              </div>
              <button
                className="icon-command"
                type="button"
                onClick={() => {
                  setSelectedAdvisor(null);
                  setShowAll(false);
                }}
                title="Close"
              >
                <X size={18} aria-hidden="true" />
              </button>
            </header>

            {selectedFigure && !showAll ? (
              <div className="advisor-state-read">
                <span>Trust: {selectedFigure.trust}</span>
                <span>Urgency: {selectedFigure.urgency}</span>
                <span>Caution: {selectedFigure.caution}</span>
                {selectedFigure.current_belief ? <p>{selectedFigure.current_belief}</p> : null}
                {selectedFigure.latest_concern ? <p>{selectedFigure.latest_concern}</p> : null}
              </div>
            ) : null}

            {proposalsToShow.map((proposal) => (
              <ProposalBlock
                proposal={proposal}
                busy={busy}
                onSelectCard={onSelectCard}
                key={proposal.advisor_id}
              />
            ))}
            {!proposalsToShow.length ? (
              <p className="empty-copy">
                {showAll ? "No advisor proposals available." : "No proposal available."}
              </p>
            ) : null}
          </section>
        </div>
      ) : null}

      <form
        className="advisor-input"
        onSubmit={(event) => {
          event.preventDefault();
          submitAsk();
        }}
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Message the council"
          rows={2}
        />
        <div className="advisor-input-actions">
          <button type="button" className="compact-command" onClick={submitAsk} disabled={Boolean(busy)}>
            <MessageSquare size={16} aria-hidden="true" />
            <span>Ask</span>
          </button>
          <button type="button" className="compact-command primary" onClick={submitOrder} disabled={Boolean(busy)}>
            <Send size={16} aria-hidden="true" />
            <span>Order</span>
          </button>
        </div>
      </form>
    </section>
  );
}

function ProposalBlock({
  proposal,
  busy,
  onSelectCard
}: {
  proposal: AdvisorProposalView;
  busy: string | null;
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
  onSelectCard
}: {
  card: ActionCardView;
  busy: string | null;
  onSelectCard: (cardId: string) => void;
}) {
  return (
    <article className={`proposal-card urgency-${card.urgency}`}>
      <div>
        <strong>{card.title}</strong>
        <p>{card.prompt_hint || card.expected_pressure_summary || card.risk_summary}</p>
        <span>
          {card.category} / {card.cost_summary || "standard bandwidth"}
        </span>
        {!card.legal_now && card.locked_reason ? (
          <span className="warning-line">{card.locked_reason}</span>
        ) : null}
      </div>
      <button
        className="compact-command primary"
        type="button"
        onClick={() => onSelectCard(card.card_id)}
        disabled={!card.legal_now || Boolean(busy)}
      >
        <Plus size={15} aria-hidden="true" />
        <span>Add</span>
      </button>
    </article>
  );
}
