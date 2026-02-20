import type { BotState, BuildStep } from '../../types';
import { BuildQueueEditor } from './BuildQueueEditor';
import { FarmThreshold } from './FarmThreshold';
import { FeatureToggles } from './FeatureToggles';
import { VillageOverrides } from './VillageOverrides';

interface Props {
  state: BotState;
  sendAction: (action: string, value: string) => void;
}

export function ConfigTab({ state, sendAction }: Props) {
  const vid = state.active_village_id;
  const vidStr = String(vid);
  const steps: BuildStep[] = state.build_queues[vidStr] ?? [];
  const levels: Record<string, number> = state.building_levels[vidStr] ?? {};

  return (
    <div className="tab-content">
      <div className="section">
        <h3>Global Features</h3>
        <FeatureToggles
          toggles={state.toggle_states}
          troopsModeLabel={state.troops_mode_label}
        />
      </div>

      <div className="section">
        <h3>Farming</h3>
        <FarmThreshold threshold={state.farm_lc_threshold} />
      </div>

      <div className="section">
        <h3>Build Queue</h3>
        <BuildQueueEditor villageId={vid} steps={steps} levels={levels} />
      </div>

      <div className="section">
        <h3>Per-Village Overrides</h3>
        <VillageOverrides state={state} sendAction={sendAction} />
      </div>
    </div>
  );
}
