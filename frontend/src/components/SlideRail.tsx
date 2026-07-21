import { ChevronLeft, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

type SlideRailProps = {
  side: "left" | "right";
  title: string;
  attentionKey?: string;
  children: ReactNode;
};

export function SlideRail({ side, title, attentionKey, children }: SlideRailProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [seenKey, setSeenKey] = useState<string>();
  const Icon = railIcon(side, isOpen);
  const action = isOpen ? "Hide" : "Show";
  const hasAttention = Boolean(attentionKey && attentionKey !== seenKey);

  return (
    <aside className={`slide-rail ${side} ${isOpen ? "open" : "closed"}`} aria-label={title}>
      <button
        className="rail-toggle"
        type="button"
        onClick={() => {
          if (!isOpen && attentionKey) setSeenKey(attentionKey);
          setIsOpen((current) => !current);
        }}
        aria-label={`${action} ${title}`}
        aria-expanded={isOpen}
        title={`${action} ${title}`}
      >
        <Icon size={20} aria-hidden="true" />
        <span>{title}</span>
        {hasAttention ? <b>New</b> : null}
      </button>
      <div className="rail-body" aria-hidden={!isOpen}>
        <header className="rail-body-header">{title}</header>
        {children}
      </div>
    </aside>
  );
}

function railIcon(side: SlideRailProps["side"], isOpen: boolean) {
  if (side === "left") {
    return isOpen ? ChevronLeft : ChevronRight;
  }
  return isOpen ? ChevronRight : ChevronLeft;
}
