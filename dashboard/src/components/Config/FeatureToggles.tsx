import { api } from '../../hooks/useApi';

interface Props {
  toggles: Record<string, boolean>;
  troopsModeLabel: string;
}

const FEATURES = [
  { key: 'building', label: 'Building' },
  { key: 'farming', label: 'Farming' },
  { key: 'scavenging', label: 'Scavenging' },
  { key: 'troops', label: 'Troops' },
];

export function FeatureToggles({ toggles, troopsModeLabel }: Props) {
  const handleToggle = async (feature: string) => {
    const current = toggles[feature] ?? false;
    await api.toggleFeature(feature, !current);
  };

  return (
    <div>
      {FEATURES.map((f) => {
        const enabled = toggles[f.key] ?? false;
        return (
          <div key={f.key} className="feature-row">
            <span className="feature-name">
              {f.label}
              {f.key === 'troops' && troopsModeLabel ? (
                <span style={{ color: 'var(--text-secondary)', fontSize: '11px', marginLeft: 6 }}>
                  {troopsModeLabel}
                </span>
              ) : null}
            </span>
            <button
              className={`toggle-btn ${enabled ? 'on' : 'off'}`}
              onClick={() => handleToggle(f.key)}
            >
              {enabled ? 'ON' : 'OFF'}
            </button>
          </div>
        );
      })}
    </div>
  );
}
