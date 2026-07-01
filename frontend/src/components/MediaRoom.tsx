import { Send } from "lucide-react";
import type { CSSProperties } from "react";
import { useState } from "react";
import type { GameView } from "../api/types";
import { roomAssets } from "../assets";

type MediaPanel = "public" | "backchannels";

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
      <div className={`media-layout focus-${activePanel}`}>
        <section
          className={`media-feed media-panel public-panel ${
            activePanel === "public" ? "active" : "collapsed"
          }`}
          aria-label="Public news"
        >
          <button
            className="media-panel-toggle"
            type="button"
            onClick={() => setActivePanel("public")}
            aria-expanded={activePanel === "public"}
          >
            <span>Public Channel</span>
            <h2>Breaking News</h2>
          </button>
          <div className="news-stack media-panel-body">
            {room.news_items.map((item) => (
              <article className={`news-item urgency-${item.urgency}`} key={item.item_id}>
                <span>{item.source}</span>
                <strong>{item.title}</strong>
                <p>{item.summary}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          className={`media-feed media-panel backchannels-panel ${
            activePanel === "backchannels" ? "active" : "collapsed"
          }`}
          aria-label="Backchannels"
        >
          <button
            className="media-panel-toggle"
            type="button"
            onClick={() => setActivePanel("backchannels")}
            aria-expanded={activePanel === "backchannels"}
          >
            <span>Private Channel</span>
            <h2>Backchannels</h2>
          </button>
          <div className="thread-stack media-panel-body">
            {room.channel_threads.length ? (
              room.channel_threads.map((thread) => (
                <article className={`thread-item ${thread.unread ? "unread" : ""}`} key={thread.thread_id}>
                  <header>
                    <strong>{thread.counterpart}</strong>
                    <span>{thread.status}</span>
                  </header>
                  <p>{thread.latest || "No message text available."}</p>
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
      </div>

      {activePanel === "backchannels" ? (
        <form
          className="backchannel-input"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <input
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            placeholder="Target"
          />
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Message"
            rows={2}
          />
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
