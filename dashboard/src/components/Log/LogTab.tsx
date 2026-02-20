import { useEffect, useRef, useState } from 'react';
import type { LogEntry } from '../../types';

interface Props {
  logs: LogEntry[];
}

const FILTERS = ['all', 'info', 'warn', 'error'] as const;

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function LogTab({ logs }: Props) {
  const [filter, setFilter] = useState<string>('all');
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const filtered = filter === 'all' ? logs : logs.filter((l) => l.lvl === filter);

  // Auto-scroll to bottom on new logs
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [filtered.length, autoScroll]);

  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 40);
  };

  return (
    <div className="tab-content" style={{ display: 'flex', flexDirection: 'column' }}>
      <div className="section" style={{ flexShrink: 0 }}>
        <div className="log-filters">
          {FILTERS.map((f) => (
            <button
              key={f}
              className={filter === f ? 'active' : ''}
              onClick={() => setFilter(f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
          <span style={{ marginLeft: 'auto', color: 'var(--text-secondary)', fontSize: '10px' }}>
            {filtered.length} entries
          </span>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflowY: 'auto', padding: '0 16px 12px' }}
      >
        <div className="log-entries">
          {filtered.map((entry, i) => (
            <div key={i} className={`log-entry ${entry.lvl}`}>
              <span className="log-time">{formatTime(entry.ts)}</span>
              <span className="log-msg">{entry.msg}</span>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="empty-state">No log entries</div>
          )}
        </div>
      </div>
    </div>
  );
}
