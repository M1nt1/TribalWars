import type { BotState } from '../../types';

interface Props {
  state: BotState;
  onSelect: (vid: number) => void;
}

export function VillageSelector({ state, onSelect }: Props) {
  const { village_ids, active_village_id, village_statuses } = state;

  if (village_ids.length === 0) return null;

  return (
    <div className="village-selector">
      <select
        value={active_village_id}
        onChange={(e) => onSelect(Number(e.target.value))}
      >
        {village_ids.map((vid) => {
          const vs = village_statuses[String(vid)];
          const label = vs ? `${vs.name} (${vs.x}|${vs.y})` : `Village ${vid}`;
          return (
            <option key={vid} value={vid}>
              {label}
            </option>
          );
        })}
      </select>
    </div>
  );
}
