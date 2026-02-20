import type { BotState } from '../../types';
import { ResourceBars } from './ResourceBars';
import { Timers } from './Timers';
import { VillageInfo } from './VillageInfo';
import { VillageSelector } from './VillageSelector';

interface Props {
  state: BotState;
  onSelectVillage: (vid: number) => void;
}

export function DashboardTab({ state, onSelectVillage }: Props) {
  const vid = String(state.active_village_id);
  const village = state.village_statuses[vid];

  if (state.village_ids.length === 0) {
    return <div className="empty-state">No villages discovered yet. Start the bot to begin.</div>;
  }

  return (
    <div className="tab-content">
      <div className="section">
        <h3>Village</h3>
        <VillageSelector state={state} onSelect={onSelectVillage} />
      </div>

      <div className="section">
        <h3>Resources</h3>
        <ResourceBars village={village} />
      </div>

      <div className="section">
        <h3>Info</h3>
        <VillageInfo village={village} />
      </div>

      <div className="section">
        <h3>Timers</h3>
        <Timers timers={state.timers} />
      </div>
    </div>
  );
}
