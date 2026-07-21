import type { GameView } from "../api/types";
import { Overlay } from "./Overlay";

type DebugOverlayProps = {
  view: GameView;
  onClose: () => void;
};

export function DebugOverlay({ view, onClose }: DebugOverlayProps) {
  const debug = view.debug;

  return (
    <Overlay eyebrow="Debug" title="Session State" className="debug-overlay" onClose={onClose}>
      {debug ? (
        <>
          <div className="debug-metrics">
            <section>
              <span>World</span>
              <strong>{debug.world_schema_version}</strong>
            </section>
            <section>
              <span>LLM calls</span>
              <strong>{debug.llm_call_count}</strong>
            </section>
            <section>
              <span>Pending signals</span>
              <strong>{debug.pending_signal_count}</strong>
            </section>
          </div>
          <pre>
            {JSON.stringify(
              {
                truth_metrics: debug.truth_metrics,
                public_metrics: debug.public_metrics,
                hidden_clocks: debug.hidden_clocks,
                raw_actor_ids: debug.raw_actor_ids,
                pending_action_ids: debug.pending_action_ids,
                latest_debug_text: debug.latest_debug_text
              },
              null,
              2
            )}
          </pre>
        </>
      ) : (
        <p className="empty-copy">Debug output is hidden.</p>
      )}
    </Overlay>
  );
}
