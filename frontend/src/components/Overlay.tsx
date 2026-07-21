import { X } from "lucide-react";
import type { ReactNode } from "react";

type OverlayProps = {
  eyebrow: string;
  title: string;
  className?: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
};

export function Overlay({
  eyebrow,
  title,
  className = "",
  children,
  footer,
  onClose
}: OverlayProps) {
  return (
    <div className="overlay-backdrop" role="presentation" onClick={onClose}>
      <section
        className={`overlay ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>{eyebrow}</span>
            <h2>{title}</h2>
          </div>
          <button className="icon-command" type="button" onClick={onClose} title="Close">
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        {children}
        {footer ? <footer>{footer}</footer> : null}
      </section>
    </div>
  );
}
