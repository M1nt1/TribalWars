import { useEffect, useState } from 'react';
import type { TimerState } from '../../types';

interface Props {
  timers: Record<string, TimerState>;
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return '00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function Timers({ timers }: Props) {
  const [now, setNow] = useState(() => Date.now() / 1000);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  // Filter to active (not expired) timers
  const active = Object.entries(timers)
    .filter(([, t]) => t.end_ts > now)
    .sort(([, a], [, b]) => a.end_ts - b.end_ts);

  if (active.length === 0) return null;

  return (
    <div className="timer-list">
      {active.map(([id, timer]) => {
        const remaining = timer.end_ts - now;
        return (
          <div key={id} className="timer-item">
            <span>{timer.label}</span>
            <span className="countdown">{formatCountdown(remaining)}</span>
          </div>
        );
      })}
    </div>
  );
}
