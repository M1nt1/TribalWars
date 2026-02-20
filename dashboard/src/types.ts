/** Shared TypeScript types mirroring PanelStateStore. */

export interface LogEntry {
  ts: number;
  msg: string;
  lvl: 'info' | 'warn' | 'error' | 'debug';
}

export interface TimerState {
  label: string;
  end_ts: number;
  category: string;
}

export interface VillageStatus {
  name: string;
  x: number;
  y: number;
  points: number;
  wood: number;
  stone: number;
  iron: number;
  storage: number;
  pop: number;
  pop_max: number;
  incoming: number;
  wood_rate: number;
  stone_rate: number;
  iron_rate: number;
}

export interface VillageConfig {
  building: boolean | null;
  farming: boolean | null;
  scavenging: boolean | null;
  troops: boolean | null;
}

export interface BuildStep {
  building: string;
  level: number;
}

export interface BotState {
  logs: LogEntry[];
  timers: Record<string, TimerState>;
  village_statuses: Record<string, VillageStatus>;
  village_configs: Record<string, VillageConfig>;
  village_ids: number[];
  active_village_id: number;
  bot_state: 'stopped' | 'paused' | 'running';
  toggle_states: Record<string, boolean>;
  active_tab: string;
  troops_mode_label: string;
  log_filter: string;
  build_queues: Record<string, BuildStep[]>;
  building_levels: Record<string, Record<string, number>>;
  farm_lc_threshold: number;
  scavenge_troops: Record<string, { enabled: boolean; reserve: number }>;
}

export interface WsMessage {
  event: string;
  data: unknown;
}

export const BUILDING_LABELS: Record<string, string> = {
  main: 'Headquarters',
  barracks: 'Barracks',
  stable: 'Stable',
  garage: 'Workshop',
  watchtower: 'Watchtower',
  snob: 'Academy',
  smith: 'Smithy',
  place: 'Rally Point',
  statue: 'Statue',
  market: 'Market',
  wood: 'Timber Camp',
  stone: 'Clay Pit',
  iron: 'Iron Mine',
  farm: 'Farm',
  storage: 'Warehouse',
  hide: 'Hiding Place',
  wall: 'Wall',
};
