import type { BotState, VillageConfig } from '../../types';

interface Props {
  state: BotState;
  sendAction: (action: string, value: string) => void;
}

const FEATURES = ['building', 'farming', 'scavenging', 'troops'] as const;

function triLabel(val: boolean | null): string {
  if (val === null || val === undefined) return 'inherit';
  return val ? 'on' : 'off';
}

function nextTriState(val: boolean | null): string {
  // Cycle: null -> true -> false -> null
  if (val === null || val === undefined) return 'true';
  if (val === true) return 'false';
  return 'null';
}

export function VillageOverrides({ state, sendAction }: Props) {
  const { village_ids, village_statuses, village_configs } = state;

  if (village_ids.length <= 1) return null;

  return (
    <div>
      {village_ids.map((vid) => {
        const vs = village_statuses[String(vid)];
        const vc: VillageConfig = village_configs[String(vid)] ?? {
          building: null,
          farming: null,
          scavenging: null,
          troops: null,
        };
        const name = vs?.name ?? `Village ${vid}`;

        return (
          <div key={vid} style={{ marginBottom: 8 }}>
            <div style={{ fontWeight: 'bold', fontSize: '11px', marginBottom: 4 }}>
              {name}
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {FEATURES.map((f) => {
                const val = vc[f];
                const cls = triLabel(val);
                return (
                  <div key={f} className="override-row">
                    <span className="override-label">{f}</span>
                    <button
                      className={`tri-btn ${cls}`}
                      onClick={() =>
                        sendAction('village_toggle', `${vid}:${f}:${nextTriState(val)}`)
                      }
                    >
                      {cls.toUpperCase()}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
