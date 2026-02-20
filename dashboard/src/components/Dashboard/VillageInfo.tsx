import type { VillageStatus } from '../../types';

interface Props {
  village: VillageStatus | undefined;
}

export function VillageInfo({ village }: Props) {
  if (!village) return null;

  const items = [
    ['Coords', `${village.x}|${village.y}`],
    ['Points', village.points.toLocaleString()],
    ['Population', `${village.pop} / ${village.pop_max}`],
    ['Storage', village.storage.toLocaleString()],
    ['Incoming', village.incoming > 0 ? String(village.incoming) : 'None'],
  ];

  return (
    <div className="info-grid">
      {items.map(([key, val]) => (
        <div key={key} style={{ display: 'contents' }}>
          <span className="key">{key}</span>
          <span className={`val${key === 'Incoming' && village.incoming > 0 ? ' error' : ''}`}
            style={key === 'Incoming' && village.incoming > 0 ? { color: 'var(--error)', fontWeight: 'bold' } : undefined}
          >
            {val}
          </span>
        </div>
      ))}
    </div>
  );
}
