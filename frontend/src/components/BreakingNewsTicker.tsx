import { Radio } from "lucide-react";
import type { CSSProperties } from "react";
import type { BreakingNewsItemView } from "../api/types";
import { roomAssets } from "../assets";

type BreakingNewsTickerProps = {
  items: BreakingNewsItemView[];
  onOpenMedia: () => void;
};

export function BreakingNewsTicker({ items, onOpenMedia }: BreakingNewsTickerProps) {
  const tickerText = items.length
    ? items.map((item) => `${item.title}: ${item.summary}`).join("   //   ")
    : "No public bulletin";

  return (
    <button
      className="news-ticker"
      type="button"
      onClick={onOpenMedia}
      style={{ "--ticker-bg": `url(${roomAssets.ticker})` } as CSSProperties}
      title="Open Media and Channels"
    >
      <Radio size={16} aria-hidden="true" />
      <span className="ticker-track">
        <span>{tickerText}</span>
      </span>
    </button>
  );
}
