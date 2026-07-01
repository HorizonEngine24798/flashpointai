import { FolderOpen, LogOut, Save, X } from "lucide-react";
import { useState } from "react";
import type { GameView } from "../api/types";

type SettingsOverlayProps = {
  view: GameView | null;
  busy: string | null;
  onClose: () => void;
  onSave: (name: string) => void;
  onLoad: (saveId: string) => void;
  onExit: () => void;
};

export function SettingsOverlay({
  view,
  busy,
  onClose,
  onSave,
  onLoad,
  onExit
}: SettingsOverlayProps) {
  const [saveName, setSaveName] = useState("");
  const saves = view?.saves ?? [];
  const settings = view?.settings;

  return (
    <div className="overlay-backdrop" role="presentation" onClick={onClose}>
      <section
        className="overlay settings-overlay"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>Session</span>
            <h2>Settings</h2>
          </div>
          <button className="icon-command" type="button" onClick={onClose} title="Close">
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="settings-grid">
          <section className="settings-section">
            <h3>Save</h3>
            <div className="save-row">
              <input
                value={saveName}
                onChange={(event) => setSaveName(event.target.value)}
                placeholder="Save name"
              />
              <button
                className="compact-command primary"
                type="button"
                onClick={() => {
                  onSave(saveName);
                  setSaveName("");
                }}
                disabled={Boolean(busy) || !view}
              >
                <Save size={16} aria-hidden="true" />
                <span>Save</span>
              </button>
            </div>
          </section>

          <section className="settings-section">
            <h3>Load</h3>
            <div className="save-list">
              {saves.length ? (
                saves.map((save) => (
                  <article className={!save.compatible ? "disabled-save" : ""} key={save.save_id}>
                    <div>
                      <strong>{save.display_name}</strong>
                      <span>
                        {save.scenario_title || save.scenario_id} - turn {save.turn_number}
                      </span>
                    </div>
                    <button
                      className="compact-command"
                      type="button"
                      disabled={Boolean(busy) || !save.compatible}
                      onClick={() => {
                        if (window.confirm("Load this save and replace the current session?")) {
                          onLoad(save.save_id);
                        }
                      }}
                    >
                      <FolderOpen size={15} aria-hidden="true" />
                      <span>Load</span>
                    </button>
                  </article>
                ))
              ) : (
                <p className="empty-copy">No local saves yet.</p>
              )}
            </div>
          </section>

          <section className="settings-section">
            <h3>Pipeline</h3>
            <p className="settings-path">{settings?.config_path ?? "config/llama_cpp.local.json"}</p>
            <div className="settings-fields">
              {(settings?.fields ?? []).map((field) => (
                <label key={field.key}>
                  <span>{field.label}</span>
                  <input value={field.value} disabled={field.disabled} readOnly />
                </label>
              ))}
            </div>
          </section>
        </div>

        <footer>
          <button className="compact-command danger" type="button" onClick={onExit}>
            <LogOut size={16} aria-hidden="true" />
            <span>Exit To Menu</span>
          </button>
        </footer>
      </section>
    </div>
  );
}
