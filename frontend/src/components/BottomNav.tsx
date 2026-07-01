import { Bug, Landmark, RadioTower, Settings, Users } from "lucide-react";
import type { NavigationBadgeView } from "../api/types";
import type { RoomId } from "../state/roomState";
import { roomLabels } from "../state/roomState";

type BottomNavProps = {
  room: RoomId;
  badges: NavigationBadgeView[];
  onRoomChange: (room: RoomId) => void;
  onDebug: () => void;
  onSettings: () => void;
};

const roomIcons = {
  control: Landmark,
  advisors: Users,
  media: RadioTower
};

export function BottomNav({ room, badges, onRoomChange, onDebug, onSettings }: BottomNavProps) {
  const badgeByRoom = new Map(badges.map((badge) => [badge.room, badge]));

  return (
    <nav className="bottom-nav" aria-label="Room navigation">
      <button className="nav-icon" type="button" onClick={onDebug} title="Debug">
        <Bug size={19} aria-hidden="true" />
      </button>

      <div className="room-buttons">
        {(["control", "advisors", "media"] as RoomId[]).map((roomId) => {
          const Icon = roomIcons[roomId];
          const badge = badgeByRoom.get(roomId);
          const isActive = room === roomId;
          return (
            <button
              className={`room-button ${isActive ? "active" : ""} ${
                badge?.active ? `has-activity tone-${badge.tone}` : ""
              }`}
              type="button"
              key={roomId}
              onClick={() => onRoomChange(roomId)}
              title={roomLabels[roomId]}
              aria-current={isActive ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{roomLabels[roomId]}</span>
              {badge?.count ? <b>{badge.count}</b> : null}
            </button>
          );
        })}
      </div>

      <button className="nav-icon" type="button" onClick={onSettings} title="Settings">
        <Settings size={19} aria-hidden="true" />
      </button>
    </nav>
  );
}
