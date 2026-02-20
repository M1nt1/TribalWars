import type { VillageStatus } from '../../types';

interface Props {
  village: VillageStatus | undefined;
}

export function ResourceBars({ village }: Props) {
  if (!village) return null;

  const resources = [
    { key: 'wood', label: 'W', value: village.wood, rate: village.wood_rate },
    { key: 'stone', label: 'S', value: village.stone, rate: village.stone_rate },
    { key: 'iron', label: 'I', value: village.iron, rate: village.iron_rate },
  ] as const;

  return (
    <div>
      {resources.map((r) => {
        const pct = village.storage > 0 ? Math.min(100, (r.value / village.storage) * 100) : 0;
        return (
          <div key={r.key} className="resource-bar">
            <span className={`label ${r.key}`}>{r.label}</span>
            <div className="bar-track">
              <div
                className={`bar-fill ${r.key}`}
                style={{ width: `${pct}%` }}
              />
              <span className="bar-text">
                {r.value.toLocaleString()} / {village.storage.toLocaleString()}
              </span>
            </div>
            <span className="rate">+{r.rate}/h</span>
          </div>
        );
      })}
    </div>
  );
}
