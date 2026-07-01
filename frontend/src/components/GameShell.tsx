import type { GameView } from "../api/types";
import type { RoomId } from "../state/roomState";
import { AdvisorsRoom } from "./AdvisorsRoom";
import { BottomNav } from "./BottomNav";
import { BreakingNewsTicker } from "./BreakingNewsTicker";
import { ControlRoom } from "./ControlRoom";
import { MediaRoom } from "./MediaRoom";

type GameShellProps = {
  view: GameView;
  busy: string | null;
  room: RoomId;
  onRoomChange: (room: RoomId) => void;
  onOpenDebug: () => void;
  onOpenSettings: () => void;
  askAdvisors: (question: string) => void;
  previewPlan: (text: string) => void;
  commitPlan: () => void;
  selectCard: (cardId: string) => void;
  removeAgendaItem: (agendaItemId: string) => void;
  clearAgenda: () => void;
  commitAgenda: () => void;
  sendBackchannel: (target: string, message: string) => void;
  acceptEnding: () => void;
  rejectEnding: () => void;
};

export function GameShell({
  view,
  busy,
  room,
  onRoomChange,
  onOpenDebug,
  onOpenSettings,
  askAdvisors,
  previewPlan,
  commitPlan,
  selectCard,
  removeAgendaItem,
  clearAgenda,
  commitAgenda,
  sendBackchannel,
  acceptEnding,
  rejectEnding
}: GameShellProps) {
  const actionState = getActionState(view);

  function resolveTurn() {
    if (actionState.kind === "plan") {
      commitPlan();
      return;
    }
    if (actionState.kind === "agenda") {
      commitAgenda();
    }
  }

  return (
    <main className="game-shell">
      <BreakingNewsTicker items={view.ticker} onOpenMedia={() => onRoomChange("media")} />

      {room === "control" ? (
        <ControlRoom
          view={view}
          busy={busy}
          actionLabel={actionState.label}
          actionBlockedReason={actionState.blockedReason}
          actionDisabled={actionState.disabled}
          onResolve={resolveTurn}
          onRemoveAgenda={removeAgendaItem}
          onClearAgenda={clearAgenda}
        />
      ) : null}

      {room === "advisors" ? (
        <AdvisorsRoom
          view={view}
          busy={busy}
          onAsk={askAdvisors}
          onOrder={previewPlan}
          onSelectCard={selectCard}
          onRemoveAgenda={removeAgendaItem}
          onClearAgenda={clearAgenda}
        />
      ) : null}

      {room === "media" ? (
        <MediaRoom view={view} busy={busy} onSendBackchannel={sendBackchannel} />
      ) : null}

      {view.ending_offers[0] ? (
        <aside className="ending-offer">
          <div>
            <span>Ending Offer</span>
            <strong>{view.ending_offers[0].title}</strong>
            <p>{view.ending_offers[0].summary}</p>
          </div>
          <button className="compact-command primary" type="button" onClick={acceptEnding}>
            Accept
          </button>
          <button className="compact-command" type="button" onClick={rejectEnding}>
            Reject
          </button>
        </aside>
      ) : null}

      <BottomNav
        room={room}
        badges={view.nav_badges}
        onRoomChange={onRoomChange}
        onDebug={onOpenDebug}
        onSettings={onOpenSettings}
      />
    </main>
  );
}

function getActionState(view: GameView): {
  kind: "agenda" | "plan" | "blocked";
  label: string;
  disabled: boolean;
  blockedReason: string;
} {
  const conflicts = [
    ...view.control_room.agenda_conflicts,
    ...view.advisor_room.agenda_conflicts
  ];
  const blockingConflict = conflicts.find((conflict) => conflict.severity === "blocking");
  if (blockingConflict) {
    return {
      kind: "blocked",
      label: "Resolve Conflict",
      disabled: true,
      blockedReason: blockingConflict.summary
    };
  }
  if (view.turn.is_concluded) {
    return {
      kind: "blocked",
      label: "Concluded",
      disabled: true,
      blockedReason: "This crisis has concluded."
    };
  }
  if (view.plan_preview) {
    return {
      kind: "plan",
      label: "Execute Order",
      disabled: !view.plan_preview.is_committable,
      blockedReason:
        view.plan_preview.errors[0] ??
        view.plan_preview.warnings[0] ??
        "The freeform order is not ready."
    };
  }
  if (view.agenda.items.length) {
    return {
      kind: "agenda",
      label: "Resolve Agenda",
      disabled: !view.agenda.can_commit,
      blockedReason: view.agenda.warnings[0] ?? "The agenda is not ready."
    };
  }
  return {
    kind: "blocked",
    label: "Queue Action First",
    disabled: true,
    blockedReason: "Add a proposal or order before resolving the turn."
  };
}
