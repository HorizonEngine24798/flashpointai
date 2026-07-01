import { ArrowLeft, Play } from "lucide-react";
import type { CSSProperties } from "react";
import type { ScenarioOptionView } from "../api/types";
import { assetUrl, roomAssets } from "../assets";

type ScenarioSelectProps = {
  scenarios: ScenarioOptionView[];
  busy: string | null;
  onBack: () => void;
  onStart: (scenarioId: string) => void;
};

export function ScenarioSelect({ scenarios, busy, onBack, onStart }: ScenarioSelectProps) {
  const options = scenarios.length
    ? scenarios
    : [
        {
          scenario_id: "cuban_missile_crisis_1962",
          title: "Cuban Missile Crisis 1962",
          historical_period: "October 1962",
          description: "U.S. EXCOMM confronts Soviet missile deployment in Cuba.",
          thumbnail_asset_key: "scenarios/cuba_missile_crisis"
        }
      ];

  return (
    <main
      className="scenario-screen"
      style={{ "--room-bg": `url(${roomAssets.start})` } as CSSProperties}
    >
      <div className="screen-shade" />
      <section className="scenario-select" aria-label="Scenario selection">
        <header className="screen-header">
          <button className="icon-command" type="button" onClick={onBack} title="Back">
            <ArrowLeft size={19} aria-hidden="true" />
          </button>
          <div>
            <h1>Start New Game</h1>
            <p>Choose the crisis on the table.</p>
          </div>
        </header>

        <div className="scenario-list">
          {options.map((scenario) => (
            <article className="scenario-option" key={scenario.scenario_id}>
              <img
                src={assetUrl(scenario.thumbnail_asset_key, "scenarios/cuba_missile_crisis")}
                alt=""
              />
              <div className="scenario-copy">
                <span>{scenario.historical_period}</span>
                <h2>{scenario.title}</h2>
                <p>{scenario.description}</p>
              </div>
              <button
                className="compact-command primary"
                type="button"
                onClick={() => onStart(scenario.scenario_id)}
                disabled={Boolean(busy)}
              >
                <Play size={16} aria-hidden="true" />
                <span>Start</span>
              </button>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
