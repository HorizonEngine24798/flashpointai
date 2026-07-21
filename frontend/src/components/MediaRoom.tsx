import { Send } from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import type { GameView } from "../api/types";
import { roomAssets } from "../assets";

type MediaPanel = "public" | "backchannels";

const publicTab = {
  panel: "public",
  label: "Public feed",
  tabId: "media-public-tab",
  panelId: "media-public-panel"
} as const;

const backchannelsTab = {
  panel: "backchannels",
  label: "Backchannels",
  tabId: "media-backchannels-tab",
  panelId: "media-backchannels-panel"
} as const;

const mediaTabs = [publicTab, backchannelsTab] satisfies {
  panel: MediaPanel;
  label: string;
  tabId: string;
  panelId: string;
}[];

type MediaRoomProps = {
  view: GameView;
  busy: string | null;
  onSendBackchannel: (target: string, message: string) => void;
};

export function MediaRoom({ view, busy, onSendBackchannel }: MediaRoomProps) {
  const [target, setTarget] = useState("");
  const [message, setMessage] = useState("");
  const [activePanel, setActivePanel] = useState<MediaPanel>("public");
  const room = view.media_room;

  useEffect(() => {
    if (target && !room.channel_threads.some((thread) => thread.target_id === target)) {
      setTarget("");
    }
  }, [room.channel_threads, target]);

  function submit() {
    const nextTarget = target.trim();
    const nextMessage = message.trim();
    if (!nextTarget || !nextMessage) {
      return;
    }
    onSendBackchannel(nextTarget, nextMessage);
    setMessage("");
  }

  return (
    <section
      className="room room-media"
      style={
        {
          "--room-bg": `url(${roomAssets.media})`,
          "--static-bg": `url(${roomAssets.static})`
        } as CSSProperties
      }
    >
      <div className="media-layout">
        <div className="media-tabs" role="tablist" aria-label="Media channels">
          {mediaTabs.map((tab) => (
            <button
              className={`media-tab ${activePanel === tab.panel ? "active" : ""}`}
              id={tab.tabId}
              type="button"
              role="tab"
              aria-selected={activePanel === tab.panel}
              aria-controls={tab.panelId}
              onClick={() => setActivePanel(tab.panel)}
              key={tab.panel}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activePanel === "public" ? (
          <section
            className="media-feed"
            id={publicTab.panelId}
            role="tabpanel"
            aria-labelledby={publicTab.tabId}
          >
            <header className="media-panel-heading">
              <span>Public record</span>
              <h2>Media history</h2>
            </header>
            <div className="news-stack">
              {room.timeline.filter((entry) => entry.scope === "public").map((entry) => (
                <article className="news-item" key={entry.entry_id}>
                  <span>Turn {entry.turn} · {entry.source || "public"}</span>
                  <strong>{entry.title}</strong>
                  <p>{entry.summary}</p>
                </article>
              ))}
              {!room.timeline.some((entry) => entry.scope === "public") ? (
                <p className="empty-copy">No public reports yet. The next visible move will appear here.</p>
              ) : null}
            </div>
          </section>
        ) : (
          <section
            className="media-feed"
            id={backchannelsTab.panelId}
            role="tabpanel"
            aria-labelledby={backchannelsTab.tabId}
          >
            <header className="media-panel-heading">
              <span>Private channels</span>
              <h2>Backchannel threads</h2>
            </header>
            <div className="thread-stack">
              {room.channel_threads.length ? (
                room.channel_threads.map((thread) => (
                  <article className={`thread-item ${thread.unread ? "unread" : ""}`} key={thread.thread_id}>
                    <header>
                      <strong>{thread.counterpart}</strong>
                      <span>{thread.status}</span>
                    </header>
                    {thread.messages.length ? (
                      <div className="backchannel-messages">
                        {thread.messages.map((entry) => (
                          <p className={entry.is_player ? "player-message" : "counterpart-message"} key={entry.message_id}>
                            <strong>{entry.sender}</strong>
                            <span>{entry.text}</span>
                          </p>
                        ))}
                      </div>
                    ) : (
                      <p>{thread.latest || "No reported exchange yet."}</p>
                    )}
                    <div className="thread-meta">
                      <span>Trust: {thread.trust_band}</span>
                      <span>Leak: {thread.leak_risk_band}</span>
                      <span>Messages: {thread.messages_remaining}</span>
                    </div>
                  </article>
                ))
              ) : (
                <p className="empty-copy">No active backchannel threads.</p>
              )}
            </div>
          </section>
        )}
      </div>

      {activePanel === "backchannels" ? (
        <form
          className="backchannel-input"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <label>
            <span>Channel</span>
            <select value={target} onChange={(event) => setTarget(event.target.value)}>
              <option value="">Choose an open channel</option>
              {room.channel_threads.map((thread) => (
                <option value={thread.target_id} key={thread.thread_id}>{thread.counterpart}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Private message</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder="Write a message to the selected counterpart"
              rows={2}
            />
          </label>
          <button
            className="compact-command primary"
            type="submit"
            disabled={Boolean(busy) || !target.trim() || !message.trim()}
          >
            <Send size={16} aria-hidden="true" />
            <span>Send</span>
          </button>
        </form>
      ) : null}
    </section>
  );
}
