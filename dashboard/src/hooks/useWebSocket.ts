import { useCallback, useEffect, useRef, useState } from 'react';
import type { BotState, LogEntry, WsMessage } from '../types';

const EMPTY_STATE: BotState = {
  logs: [],
  timers: {},
  village_statuses: {},
  village_configs: {},
  village_ids: [],
  active_village_id: 0,
  bot_state: 'stopped',
  toggle_states: {},
  active_tab: 'dashboard',
  troops_mode_label: '',
  log_filter: 'all',
  build_queues: {},
  building_levels: {},
  farm_lc_threshold: 20,
  scavenge_troops: {},
};

export function useWebSocket() {
  const [state, setState] = useState<BotState>(EMPTY_STATE);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/ws`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      const msg: WsMessage = JSON.parse(evt.data);
      setState((prev) => applyEvent(prev, msg));
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const sendAction = useCallback((action: string, value: string = '') => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action, value }));
    }
  }, []);

  return { state, connected, sendAction };
}

function applyEvent(prev: BotState, msg: WsMessage): BotState {
  const { event, data } = msg;

  switch (event) {
    case 'full_state':
      return data as BotState;

    case 'bot_state':
      return { ...prev, bot_state: (data as { state: string }).state as BotState['bot_state'] };

    case 'log': {
      const entry = data as LogEntry;
      const logs = [...prev.logs, entry];
      if (logs.length > 200) logs.splice(0, logs.length - 200);
      return { ...prev, logs };
    }

    case 'timer': {
      const t = data as { id: string; label: string; end_ts: number };
      return {
        ...prev,
        timers: { ...prev.timers, [t.id]: { label: t.label, end_ts: t.end_ts, category: '' } },
      };
    }

    case 'village_status': {
      const vs = data as { village_id: number } & Record<string, unknown>;
      const vid = String(vs.village_id);
      const { village_id: _, ...rest } = vs;
      return {
        ...prev,
        village_statuses: { ...prev.village_statuses, [vid]: rest as never },
      };
    }

    case 'toggles':
      return { ...prev, toggle_states: data as Record<string, boolean> };

    case 'build_queue': {
      const bq = data as { village_id: number; steps: unknown[]; levels: Record<string, number> };
      const vid = String(bq.village_id);
      return {
        ...prev,
        build_queues: { ...prev.build_queues, [vid]: bq.steps as never },
        building_levels: { ...prev.building_levels, [vid]: bq.levels },
      };
    }

    case 'troops_mode':
      return { ...prev, troops_mode_label: (data as { label: string }).label };

    default:
      return prev;
  }
}
