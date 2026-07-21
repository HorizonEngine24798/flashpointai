import type { GameView } from "../api/types";
import type { RoomId } from "../state/roomState";
import { AdvisorsRoom } from "./AdvisorsRoom";
import { BottomNav } from "./BottomNav";
import { BreakingNewsTicker } from "./BreakingNewsTicker";
import { ControlRoom } from "./ControlRoom";
import { MediaRoom } from "./MediaRoom";

const QUEUE_ACTION = "Select an action";
const COMMIT_PLAN = "Commit freeform plan";
const RESOLVE_AGENDA = "Resolve card agenda";

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
  cancelPlan: () => void;
  selectCard: (cardId: string) => void;
  removeAgendaItem: (agendaItemId: string) => void;
  clearAgenda: () => void;
  commitAgenda: () => void;
  endTurn: () => void;
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
  cancelPlan,
  selectCard,
  removeAgendaItem,
  clearAgenda,
  commitAgenda,
  endTurn,
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
      return;
    }
    if (actionState.kind === "hold") {
      endTurn();
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
          onCancelPlan={cancelPlan}
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
          onCancelPlan={cancelPlan}
        />
      ) : null}

      {room === "media" ? (
        <MediaRoom view={view} busy={busy} onSendBackchannel={sendBackchannel} />
      ) : null}

      {view.ending_offers[0] ? (
        <aside className="ending-offer">
          <div>
            <span>Conclusion Available</span>
            <strong>{view.ending_offers[0].title}</strong>
            <p>{view.ending_offers[0].summary}</p>
          </div>
          <button
            className="compact-command primary"
            type="button"
            onClick={acceptEnding}
            disabled={Boolean(busy)}
          >
            Accept Conclusion
          </button>
          <button
            className="compact-command"
            type="button"
            onClick={rejectEnding}
            disabled={Boolean(busy)}
          >
            Continue Crisis
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
  kind: "agenda" | "plan" | "hold" | "blocked";
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
      label: QUEUE_ACTION,
      disabled: true,
      blockedReason: blockingConflict.summary
    };
  }
  if (view.turn.is_concluded) {
    return {
      kind: "blocked",
      label: QUEUE_ACTION,
      disabled: true,
      blockedReason: "This crisis has concluded."
    };
  }
  if (view.plan_preview) {
    return {
      kind: "plan",
      label: COMMIT_PLAN,
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
      label: RESOLVE_AGENDA,
      disabled: !view.agenda.can_commit,
      blockedReason: view.agenda.warnings[0] ?? "The agenda is not ready."
    };
  }
  return {
    kind: "hold",
    label: "Hold position",
    disabled: false,
    blockedReason: "Resolve the turn without a formal action."
  };
}
