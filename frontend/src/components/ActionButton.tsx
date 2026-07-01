import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import type { CSSProperties } from "react";
import { roomAssets } from "../assets";

type ActionButtonProps = {
  label: string;
  blockedReason: string;
  busy: string | null;
  disabled: boolean;
  onAction: () => void;
};

export function ActionButton({
  label,
  blockedReason,
  busy,
  disabled,
  onAction
}: ActionButtonProps) {
  const isBusy = Boolean(busy);
  const Icon = isBusy ? Loader2 : disabled ? AlertTriangle : CheckCircle2;

  return (
    <div className="action-button-wrap">
      <button
        className="action-button"
        type="button"
        onClick={onAction}
        disabled={disabled || isBusy}
        style={
          {
            "--action-idle": `url(${roomAssets.actionIdle})`,
            "--action-hover": `url(${roomAssets.actionHover})`,
            "--action-pressed": `url(${roomAssets.actionPressed})`,
            "--action-disabled": `url(${roomAssets.actionDisabled})`
          } as CSSProperties
        }
      >
        <Icon className={isBusy ? "spin" : ""} size={22} aria-hidden="true" />
        <span>{isBusy ? busy : label}</span>
      </button>
      {disabled && !isBusy && blockedReason ? (
        <span className="action-blocked">{blockedReason}</span>
      ) : null}
    </div>
  );
}
