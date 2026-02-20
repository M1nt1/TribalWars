"""Injected side panel for in-browser bot control and status display.

Communication uses console.log('STAEMME:action') from JS -> Python
because patchright's expose_function breaks DNS resolution.

Overhauled: 450px tabbed panel with persistent logs, client-side timers,
resource bars, village selector, per-village config.  All state lives in
PanelStateStore (Python-side) and is re-hydrated after every DOM reset.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from staemme.core.logging import get_logger
from staemme.core.panel_interface import PanelInterface
from staemme.core.panel_state import PanelStateStore, VillageStatus
from staemme.models.buildings import BUILDING_LABELS

if TYPE_CHECKING:
    from staemme.core.browser_client import BrowserClient

log = get_logger("panel")

ACTION_PREFIX = "STAEMME:"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
PANEL_CSS = r"""
#staemme-panel {
  position: fixed; top: 0; right: 0; width: 450px; height: 100vh;
  background: #1a1a2e; color: #e0e0e0;
  font-family: 'Segoe UI', Tahoma, sans-serif; font-size: 12px;
  z-index: 99999; box-shadow: -2px 0 8px rgba(0,0,0,0.5);
  display: flex; flex-direction: column; overflow: hidden;
}
#staemme-panel * { box-sizing: border-box; }

/* Header */
#staemme-panel .sp-header {
  background: #16213e; padding: 8px 12px; font-size: 14px; font-weight: bold;
  border-bottom: 2px solid #0f3460; display: flex; align-items: center; gap: 8px;
  flex-shrink: 0;
}
#staemme-panel .sp-dot {
  width: 10px; height: 10px; border-radius: 50%; background: #666; flex-shrink: 0;
}
#staemme-panel .sp-dot.running { background: #4ecca3; }
#staemme-panel .sp-dot.paused  { background: #f0c040; }
#staemme-panel .sp-dot.stopped { background: #e74c3c; }
#staemme-panel .sp-controls { display: flex; gap: 4px; margin-left: auto; }
#staemme-panel .sp-btn {
  padding: 4px 10px; border: none; border-radius: 3px;
  cursor: pointer; font-size: 10px; font-weight: bold; color: #fff;
}
#staemme-panel .sp-btn-start { background: #4ecca3; }
#staemme-panel .sp-btn-pause { background: #f0c040; color: #1a1a2e; }
#staemme-panel .sp-btn-stop  { background: #e74c3c; }

/* Tabs */
#staemme-panel .sp-tabs {
  display: flex; background: #16213e; border-bottom: 1px solid #0f3460; flex-shrink: 0;
}
#staemme-panel .sp-tab {
  flex: 1; padding: 7px 0; text-align: center; cursor: pointer;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  color: #888; border-bottom: 2px solid transparent; transition: all 0.2s;
}
#staemme-panel .sp-tab:hover { color: #ccc; }
#staemme-panel .sp-tab.active { color: #4ecca3; border-bottom-color: #4ecca3; }

/* Tab content */
#staemme-panel .sp-tab-content { display: none; flex: 1; overflow-y: auto; }
#staemme-panel .sp-tab-content.active { display: flex; flex-direction: column; }

/* Section */
#staemme-panel .sp-section { padding: 8px 12px; border-bottom: 1px solid #0f3460; }
#staemme-panel .sp-section h3 {
  margin: 0 0 6px 0; font-size: 10px; text-transform: uppercase;
  color: #4ecca3; letter-spacing: 0.5px;
}

/* Village selector */
#staemme-panel .sp-village-search {
  width: 100%; padding: 4px 8px; background: #0d0d1a; border: 1px solid #0f3460;
  color: #e0e0e0; border-radius: 3px; font-size: 11px; margin-bottom: 4px;
}
#staemme-panel .sp-village-list {
  max-height: 80px; overflow-y: auto; background: #0d0d1a; border-radius: 3px;
}
#staemme-panel .sp-village-item {
  padding: 3px 8px; cursor: pointer; font-size: 11px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
#staemme-panel .sp-village-item:hover { background: #16213e; }
#staemme-panel .sp-village-item.active { background: #0f3460; color: #4ecca3; }

/* Resource bars */
#staemme-panel .sp-res-row {
  display: flex; align-items: center; gap: 6px; margin-bottom: 3px;
}
#staemme-panel .sp-res-icon { width: 14px; font-weight: bold; font-size: 10px; }
#staemme-panel .sp-res-bar {
  flex: 1; height: 12px; background: #0d0d1a; border-radius: 2px; overflow: hidden;
  position: relative;
}
#staemme-panel .sp-res-fill {
  height: 100%; border-radius: 2px; transition: width 0.3s;
}
#staemme-panel .sp-res-fill.wood  { background: #8B6914; }
#staemme-panel .sp-res-fill.stone { background: #707070; }
#staemme-panel .sp-res-fill.iron  { background: #4a7c59; }
#staemme-panel .sp-res-val {
  font-size: 10px; min-width: 70px; text-align: right; white-space: nowrap;
}
#staemme-panel .sp-res-rate { font-size: 9px; color: #888; min-width: 40px; }

/* Info grid */
#staemme-panel .sp-info-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 2px 8px; font-size: 11px;
}
#staemme-panel .sp-info-grid .lbl { color: #888; }
#staemme-panel .sp-info-grid .val { text-align: right; }

/* Timers */
#staemme-panel .sp-timer-row {
  display: flex; justify-content: space-between; padding: 2px 0;
  font-family: 'Consolas', monospace; font-size: 11px;
}
#staemme-panel .sp-timer-label { color: #888; }
#staemme-panel .sp-timer-value { color: #4ecca3; }

/* Config toggles */
#staemme-panel .sp-feature-row {
  display: flex; align-items: center; gap: 6px; padding: 3px 0;
}
#staemme-panel .sp-onoff {
  padding: 2px 8px; border: none; border-radius: 3px; cursor: pointer;
  font-size: 10px; font-weight: bold; min-width: 32px; text-align: center;
}
#staemme-panel .sp-onoff.on  { background: #4ecca3; color: #1a1a2e; }
#staemme-panel .sp-onoff.off { background: #e74c3c; color: #fff; }
#staemme-panel .sp-cfg-section { margin-top: 8px; }
#staemme-panel .sp-cfg-section h4 {
  margin: 0 0 4px 0; font-size: 10px; color: #888; text-transform: uppercase;
}
#staemme-panel .sp-tri-toggle {
  display: flex; align-items: center; gap: 6px; padding: 2px 0; font-size: 11px;
}
#staemme-panel .sp-tri-btn {
  padding: 1px 6px; border: 1px solid #0f3460; background: #0d0d1a;
  color: #888; cursor: pointer; font-size: 9px; border-radius: 2px;
}
#staemme-panel .sp-tri-btn.active-inherit { border-color: #888; color: #e0e0e0; }
#staemme-panel .sp-tri-btn.active-on { border-color: #4ecca3; color: #4ecca3; }
#staemme-panel .sp-tri-btn.active-off { border-color: #e74c3c; color: #e74c3c; }

/* Log */
#staemme-panel .sp-log-filters {
  display: flex; gap: 4px; margin-bottom: 4px;
}
#staemme-panel .sp-log-filter-btn {
  padding: 2px 8px; border: 1px solid #0f3460; background: #0d0d1a;
  color: #888; cursor: pointer; font-size: 10px; border-radius: 2px;
}
#staemme-panel .sp-log-filter-btn.active { border-color: #4ecca3; color: #4ecca3; }
#staemme-panel .sp-log {
  flex: 1; min-height: 100px; overflow-y: auto; padding: 4px 8px;
  font-family: 'Consolas', monospace; font-size: 11px; line-height: 1.4;
  background: #0d0d1a;
}
#staemme-panel .sp-log .log-info  { color: #4ecca3; }
#staemme-panel .sp-log .log-warn  { color: #f0c040; }
#staemme-panel .sp-log .log-error { color: #e74c3c; }
#staemme-panel .sp-log .log-debug { color: #666; }

/* Build Queue */
#staemme-panel .sp-bq-add-row {
  display: flex; gap: 4px; margin-bottom: 6px; align-items: center;
}
#staemme-panel .sp-bq-add-row select,
#staemme-panel .sp-bq-add-row input {
  background: #0d0d1a; border: 1px solid #0f3460; color: #e0e0e0;
  border-radius: 3px; font-size: 11px; padding: 3px 4px;
}
#staemme-panel .sp-bq-add-row select { flex: 1; }
#staemme-panel .sp-bq-add-row input[type=number] { width: 42px; text-align: center; }
#staemme-panel .sp-bq-btn {
  padding: 3px 8px; border: none; border-radius: 3px; cursor: pointer;
  font-size: 10px; font-weight: bold; color: #fff; background: #4ecca3;
}
#staemme-panel .sp-bq-btn:hover { background: #3dba91; }
#staemme-panel .sp-bq-clear {
  font-size: 10px; color: #e74c3c; cursor: pointer; text-decoration: underline;
  background: none; border: none; padding: 0;
}
#staemme-panel .sp-bq-list { list-style: none; padding: 0; margin: 0; }
#staemme-panel .sp-bq-item {
  display: flex; align-items: center; gap: 4px; padding: 3px 4px;
  border-bottom: 1px solid #0f3460; font-size: 11px;
}
#staemme-panel .sp-bq-item.completed { opacity: 0.5; }
#staemme-panel .sp-bq-idx { color: #888; min-width: 16px; }
#staemme-panel .sp-bq-name { flex: 1; }
#staemme-panel .sp-bq-cur { color: #888; font-size: 10px; margin-left: 4px; }
#staemme-panel .sp-bq-actions { display: flex; gap: 2px; }
#staemme-panel .sp-bq-actions button {
  background: #0d0d1a; border: 1px solid #0f3460; color: #888;
  cursor: pointer; font-size: 10px; padding: 1px 4px; border-radius: 2px;
}
#staemme-panel .sp-bq-actions button:hover { color: #e0e0e0; border-color: #4ecca3; }
#staemme-panel .sp-bq-empty { color: #666; font-size: 10px; font-style: italic; }

/* Bot protection alert banner */
#staemme-panel .sp-alert-banner {
  display: none; background: #e74c3c; color: #fff; padding: 8px 12px;
  font-size: 12px; font-weight: bold; text-align: center;
  animation: sp-pulse 1.5s ease-in-out infinite; flex-shrink: 0;
}
#staemme-panel .sp-alert-banner.active { display: block; }
@keyframes sp-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

body { margin-right: 450px !important; }
"""

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
PANEL_HTML = """
<div id="staemme-panel">
  <!-- Header -->
  <div class="sp-header">
    <span class="sp-dot" id="sp-status-dot"></span>
    <span>Staemme Bot</span>
    <span id="sp-status-text" style="margin-left:4px;font-size:11px;color:#888">Idle</span>
    <div class="sp-controls">
      <button class="sp-btn sp-btn-start" onclick="console.log('STAEMME:start')">Start</button>
      <button class="sp-btn sp-btn-pause" onclick="console.log('STAEMME:pause')">Pause</button>
      <button class="sp-btn sp-btn-stop"  onclick="console.log('STAEMME:stop')">Stop</button>
    </div>
  </div>

  <!-- Bot Protection Alert -->
  <div class="sp-alert-banner" id="sp-alert-banner">
    <span id="sp-alert-text">BOT PROTECTION DETECTED</span>
    <button id="sp-alert-resolve" onclick="console.log('STAEMME:bot_protection_resolved')"
      style="margin-left:8px;padding:2px 10px;border:2px solid #fff;border-radius:3px;background:transparent;color:#fff;font-size:11px;font-weight:bold;cursor:pointer">
      Resolved</button>
  </div>

  <!-- Tabs -->
  <div class="sp-tabs">
    <div class="sp-tab active" data-tab="dashboard"
         onclick="console.log('STAEMME:tab_switch:dashboard')">Dashboard</div>
    <div class="sp-tab" data-tab="config"
         onclick="console.log('STAEMME:tab_switch:config')">Config</div>
    <div class="sp-tab" data-tab="log"
         onclick="console.log('STAEMME:tab_switch:log')">Log</div>
  </div>

  <!-- Dashboard tab -->
  <div class="sp-tab-content active" id="sp-tc-dashboard">
    <div class="sp-section">
      <h3>Village</h3>
      <input class="sp-village-search" id="sp-vsearch" placeholder="Search villages..."
             oninput="window.__sp._filterVillages(this.value)">
      <div class="sp-village-list" id="sp-vlist"></div>
    </div>
    <div class="sp-section">
      <h3>Resources</h3>
      <div id="sp-resources">
        <div class="sp-res-row"><span class="sp-res-icon" style="color:#8B6914">W</span>
          <div class="sp-res-bar"><div class="sp-res-fill wood" id="sp-bar-wood" style="width:0%"></div></div>
          <span class="sp-res-val" id="sp-val-wood">-</span>
          <span class="sp-res-rate" id="sp-rate-wood"></span></div>
        <div class="sp-res-row"><span class="sp-res-icon" style="color:#707070">S</span>
          <div class="sp-res-bar"><div class="sp-res-fill stone" id="sp-bar-stone" style="width:0%"></div></div>
          <span class="sp-res-val" id="sp-val-stone">-</span>
          <span class="sp-res-rate" id="sp-rate-stone"></span></div>
        <div class="sp-res-row"><span class="sp-res-icon" style="color:#4a7c59">I</span>
          <div class="sp-res-bar"><div class="sp-res-fill iron" id="sp-bar-iron" style="width:0%"></div></div>
          <span class="sp-res-val" id="sp-val-iron">-</span>
          <span class="sp-res-rate" id="sp-rate-iron"></span></div>
      </div>
    </div>
    <div class="sp-section">
      <h3>Info</h3>
      <div class="sp-info-grid" id="sp-info">
        <span class="lbl">Coords</span><span class="val" id="sp-info-coords">-</span>
        <span class="lbl">Points</span><span class="val" id="sp-info-points">-</span>
        <span class="lbl">Pop</span><span class="val" id="sp-info-pop">-</span>
        <span class="lbl">Storage</span><span class="val" id="sp-info-storage">-</span>
        <span class="lbl">Incoming</span><span class="val" id="sp-info-incoming" style="color:#e0e0e0">0</span>
      </div>
    </div>
    <div class="sp-section">
      <h3>Timers</h3>
      <div id="sp-timers"></div>
    </div>
  </div>

  <!-- Config tab -->
  <div class="sp-tab-content" id="sp-tc-config">
    <div class="sp-section">
      <h3>Global Features</h3>
      <div class="sp-toggles" id="sp-global-toggles">
        <div class="sp-feature-row">
          <button class="sp-onoff off" id="sp-toggle-building"
            onclick="window.__sp._toggleFeature('building')">OFF</button>
          <span>Building</span>
        </div>
        <div class="sp-feature-row">
          <button class="sp-onoff off" id="sp-toggle-farming"
            onclick="window.__sp._toggleFeature('farming')">OFF</button>
          <span>Farming</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;margin-top:2px;margin-left:40px">
          <span style="font-size:10px;color:#888">LC Threshold:</span>
          <input type="number" id="sp-farm-threshold" min="1" max="100" value="20"
            style="width:42px;background:#0d0d1a;border:1px solid #0f3460;color:#e0e0e0;border-radius:3px;font-size:11px;padding:2px 4px;text-align:center"
            onchange="console.log('STAEMME:farm_threshold:'+this.value)">
        </div>
        <div class="sp-feature-row">
          <button class="sp-onoff off" id="sp-toggle-scavenging"
            onclick="window.__sp._toggleFeature('scavenging')">OFF</button>
          <span>Scavenging</span>
        </div>
        <div id="sp-scav-troops" style="margin-left:20px;margin-top:4px"></div>
        <div class="sp-feature-row">
          <button class="sp-onoff off" id="sp-toggle-troops"
            onclick="window.__sp._toggleFeature('troops')">OFF</button>
          <span>Troops <span id="sp-troops-mode" style="color:#888;font-size:10px"></span></span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;margin-top:2px;margin-left:40px">
          <span style="font-size:10px;color:#888">Train Unit:</span>
          <select id="sp-fill-unit"
            style="background:#0d0d1a;border:1px solid #0f3460;color:#e0e0e0;border-radius:3px;font-size:11px;padding:2px 4px"
            onchange="console.log('STAEMME:fill_unit:'+this.value)">
            <option value="spear">Spear</option>
            <option value="sword">Sword</option>
            <option value="axe">Axe</option>
            <option value="archer">Archer</option>
          </select>
        </div>
      </div>
    </div>
    <div class="sp-section">
      <h3 style="display:flex;justify-content:space-between;align-items:center">
        Build Queue
        <button class="sp-bq-clear" onclick="console.log('STAEMME:bq_clear')">Clear All</button>
      </h3>
      <div class="sp-bq-add-row">
        <select id="sp-bq-select"></select>
        <input type="number" id="sp-bq-level" min="1" max="30" value="2" style="width:42px">
        <button class="sp-bq-btn" onclick="window.__sp._bqAdd()">+Add</button>
      </div>
      <ul class="sp-bq-list" id="sp-bq-list"></ul>
    </div>
    <div class="sp-section">
      <h3>Per-Village Overrides</h3>
      <div id="sp-village-cfg"></div>
    </div>
  </div>

  <!-- Log tab -->
  <div class="sp-tab-content" id="sp-tc-log">
    <div class="sp-section" style="flex:1;display:flex;flex-direction:column;min-height:0;padding-bottom:0;border:0">
      <div class="sp-log-filters" id="sp-log-filters">
        <button class="sp-log-filter-btn active" data-level="all"
          onclick="console.log('STAEMME:log_filter:all')">All</button>
        <button class="sp-log-filter-btn" data-level="info"
          onclick="console.log('STAEMME:log_filter:info')">Info</button>
        <button class="sp-log-filter-btn" data-level="warn"
          onclick="console.log('STAEMME:log_filter:warn')">Warn</button>
        <button class="sp-log-filter-btn" data-level="error"
          onclick="console.log('STAEMME:log_filter:error')">Error</button>
      </div>
      <div class="sp-log" id="sp-log"></div>
    </div>
  </div>
</div>
"""

# ---------------------------------------------------------------------------
# JS — all in window.__sp namespace
# ---------------------------------------------------------------------------
PANEL_JS = r"""
window.__sp = {
  _state: null,
  _timerInterval: null,

  hydrate: function(state) {
    this._state = state;
    this._switchTabUI(state.active_tab || 'dashboard');
    this._renderBotState(state.bot_state || 'stopped');
    this._renderVillageList();
    this._renderDashboard();
    this._renderTimers();
    this._startTimers();
    this._renderConfig();
    this._renderLog();
    this._initBqSelect();
    this._bqAutoLevel();
    this._renderBuildQueue();
    this.pushBotProtection(state.bot_protection_detected, state.bot_protection_pattern);
  },

  /* ---- Bot state ---- */
  _renderBotState: function(st) {
    var dot = document.getElementById('sp-status-dot');
    var txt = document.getElementById('sp-status-text');
    if (dot) dot.className = 'sp-dot ' + st;
    if (txt) txt.textContent = st.charAt(0).toUpperCase() + st.slice(1);
  },

  /* ---- Tab switching ---- */
  _switchTabUI: function(tab) {
    var tabs = document.querySelectorAll('#staemme-panel .sp-tab');
    var contents = document.querySelectorAll('#staemme-panel .sp-tab-content');
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i].getAttribute('data-tab');
      if (t === tab) { tabs[i].classList.add('active'); }
      else { tabs[i].classList.remove('active'); }
    }
    for (var j = 0; j < contents.length; j++) {
      if (contents[j].id === 'sp-tc-' + tab) { contents[j].classList.add('active'); }
      else { contents[j].classList.remove('active'); }
    }
  },

  /* ---- Village list ---- */
  _renderVillageList: function() {
    var el = document.getElementById('sp-vlist');
    if (!el || !this._state) return;
    el.innerHTML = '';
    var ids = this._state.village_ids || [];
    var active = this._state.active_village_id;
    var statuses = this._state.village_statuses || {};
    for (var i = 0; i < ids.length; i++) {
      var vid = ids[i];
      var vs = statuses[vid];
      var name = vs ? vs.name : 'Village ' + vid;
      var d = document.createElement('div');
      d.className = 'sp-village-item' + (vid === active ? ' active' : '');
      d.setAttribute('data-vid', vid);
      d.textContent = name + ' (' + vid + ')';
      d.onclick = (function(id) { return function() { console.log('STAEMME:select_village:' + id); }; })(vid);
      el.appendChild(d);
    }
  },

  _filterVillages: function(query) {
    var items = document.querySelectorAll('#sp-vlist .sp-village-item');
    var q = (query || '').toLowerCase();
    for (var i = 0; i < items.length; i++) {
      var text = items[i].textContent.toLowerCase();
      items[i].style.display = (!q || text.indexOf(q) >= 0) ? '' : 'none';
    }
  },

  /* ---- Dashboard ---- */
  _renderDashboard: function() {
    if (!this._state) return;
    var vid = this._state.active_village_id;
    var vs = (this._state.village_statuses || {})[vid];
    if (!vs) return;

    var storage = vs.storage || 1;
    var fmt = function(n) { return n.toLocaleString('de-DE'); };

    // Resource bars
    var res = ['wood', 'stone', 'iron'];
    for (var i = 0; i < res.length; i++) {
      var r = res[i];
      var bar = document.getElementById('sp-bar-' + r);
      var val = document.getElementById('sp-val-' + r);
      var rate = document.getElementById('sp-rate-' + r);
      var amount = vs[r] || 0;
      var pct = Math.min(100, Math.round(amount / storage * 100));
      if (bar) bar.style.width = pct + '%';
      if (val) val.textContent = fmt(amount) + ' / ' + fmt(storage);
      if (rate) {
        var rateVal = vs[r + '_rate'] || 0;
        rate.textContent = rateVal > 0 ? '+' + fmt(rateVal) + '/h' : '';
      }
    }

    // Info grid
    var setEl = function(id, text) {
      var e = document.getElementById(id);
      if (e) e.textContent = text;
    };
    setEl('sp-info-coords', vs.x + '|' + vs.y);
    setEl('sp-info-points', fmt(vs.points));
    setEl('sp-info-pop', (vs.pop || 0) + ' / ' + (vs.pop_max || 0));
    setEl('sp-info-storage', fmt(storage));
    var inc = document.getElementById('sp-info-incoming');
    if (inc) {
      inc.textContent = vs.incoming || 0;
      inc.style.color = (vs.incoming || 0) > 0 ? '#e74c3c' : '#e0e0e0';
    }
  },

  /* ---- Timers ---- */
  _renderTimers: function() {
    var el = document.getElementById('sp-timers');
    if (!el || !this._state) return;
    el.innerHTML = '';
    var timers = this._state.timers || {};
    var keys = Object.keys(timers);
    if (keys.length === 0) {
      el.innerHTML = '<div style="color:#666;font-size:10px">No active timers</div>';
      return;
    }
    for (var i = 0; i < keys.length; i++) {
      var t = timers[keys[i]];
      var row = document.createElement('div');
      row.className = 'sp-timer-row';
      row.innerHTML = '<span class="sp-timer-label">' + t.label + '</span>' +
        '<span class="sp-timer-value" data-timer-end="' + t.end_ts + '">--:--</span>';
      el.appendChild(row);
    }
    this._tickTimers();
  },

  _startTimers: function() {
    if (this._timerInterval) clearInterval(this._timerInterval);
    var self = this;
    this._timerInterval = setInterval(function() { self._tickTimers(); }, 1000);
  },

  _tickTimers: function() {
    var els = document.querySelectorAll('#sp-timers [data-timer-end]');
    var now = Date.now() / 1000;
    for (var i = 0; i < els.length; i++) {
      var end = parseFloat(els[i].getAttribute('data-timer-end'));
      var rem = Math.max(0, Math.round(end - now));
      if (rem <= 0) {
        els[i].textContent = 'Done';
        els[i].style.color = '#888';
      } else {
        var h = Math.floor(rem / 3600);
        var m = Math.floor((rem % 3600) / 60);
        var s = rem % 60;
        els[i].textContent = (h > 0 ? h + ':' : '') +
          (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
      }
    }
  },

  /* ---- Config ---- */
  _renderConfig: function() {
    if (!this._state) return;
    // Global toggles
    var toggles = this._state.toggle_states || {};
    var features = ['building', 'farming', 'scavenging', 'troops'];
    for (var i = 0; i < features.length; i++) {
      var btn = document.getElementById('sp-toggle-' + features[i]);
      if (btn && toggles[features[i]] !== undefined) {
        var on = !!toggles[features[i]];
        btn.textContent = on ? 'ON' : 'OFF';
        btn.className = 'sp-onoff ' + (on ? 'on' : 'off');
      }
    }
    // Farm LC threshold
    var ft = document.getElementById('sp-farm-threshold');
    if (ft && this._state.farm_lc_threshold !== undefined) {
      ft.value = this._state.farm_lc_threshold;
    }

    // Troops mode label
    var tm = document.getElementById('sp-troops-mode');
    if (tm) tm.textContent = this._state.troops_mode_label || '';

    // Fill unit dropdown
    var fu = document.getElementById('sp-fill-unit');
    if (fu && this._state.fill_unit) fu.value = this._state.fill_unit;

    // Scavenge troop config
    this._renderScavTroops();

    // Per-village overrides
    this._renderVillageConfig();
  },

  _renderScavTroops: function() {
    var el = document.getElementById('sp-scav-troops');
    if (!el || !this._state) return;
    var troops = this._state.scavenge_troops || {};
    var units = Object.keys(troops);
    if (units.length === 0) { el.innerHTML = ''; return; }
    var html = '<div style="font-size:10px;color:#888;margin-bottom:2px">Scavenge Units:</div>';
    for (var i = 0; i < units.length; i++) {
      var u = units[i];
      var t = troops[u];
      var checked = t.enabled ? ' checked' : '';
      var name = u.charAt(0).toUpperCase() + u.slice(1);
      html += '<div style="display:flex;align-items:center;gap:6px;padding:1px 0">';
      html += '<label style="display:flex;align-items:center;gap:4px;cursor:pointer;min-width:80px">';
      html += '<input type="checkbox" id="sp-scav-' + u + '"' + checked;
      html += ' onchange="console.log(\'STAEMME:scav_troop:' + u + ':enabled:\'+this.checked)"';
      html += ' style="accent-color:#4ecca3">';
      html += '<span style="font-size:10px">' + name + '</span></label>';
      if (t.enabled) {
        html += '<span style="font-size:9px;color:#888">Reserve:</span>';
        html += '<input type="number" min="0" max="9999" value="' + (t.reserve || 0) + '"';
        html += ' style="width:40px;background:#0d0d1a;border:1px solid #0f3460;color:#e0e0e0;border-radius:3px;font-size:10px;padding:1px 3px;text-align:center"';
        html += ' onchange="console.log(\'STAEMME:scav_troop:' + u + ':reserve:\'+this.value)">';
      }
      html += '</div>';
    }
    el.innerHTML = html;
  },

  _renderVillageConfig: function() {
    var el = document.getElementById('sp-village-cfg');
    if (!el || !this._state) return;
    el.innerHTML = '';
    var ids = this._state.village_ids || [];
    var configs = this._state.village_configs || {};
    var statuses = this._state.village_statuses || {};
    var features = ['building', 'farming', 'scavenging', 'troops'];

    for (var i = 0; i < ids.length; i++) {
      var vid = ids[i];
      var vs = statuses[vid];
      var vc = configs[vid] || {};
      var name = vs ? vs.name : 'Village ' + vid;

      var sec = document.createElement('div');
      sec.className = 'sp-cfg-section';
      sec.innerHTML = '<h4>' + name + '</h4>';

      for (var j = 0; j < features.length; j++) {
        var feat = features[j];
        var val = vc[feat]; // null=inherit, true=on, false=off
        var row = document.createElement('div');
        row.className = 'sp-tri-toggle';

        var mkBtn = function(v, label, cls, vid2, feat2) {
          return '<button class="sp-tri-btn ' + cls + '" ' +
            'onclick="console.log(\'STAEMME:village_toggle:' + vid2 + ':' + feat2 + ':' + v + '\')">' +
            label + '</button>';
        };
        row.innerHTML =
          mkBtn('null', 'Inherit', val === null || val === undefined ? 'active-inherit' : '', vid, feat) +
          mkBtn('true', 'On', val === true ? 'active-on' : '', vid, feat) +
          mkBtn('false', 'Off', val === false ? 'active-off' : '', vid, feat) +
          ' <span style="margin-left:4px">' + feat + '</span>';
        sec.appendChild(row);
      }
      el.appendChild(sec);
    }
  },

  /* ---- Log ---- */
  _renderLog: function() {
    var el = document.getElementById('sp-log');
    if (!el || !this._state) return;
    el.innerHTML = '';
    var logs = this._state.logs || [];
    var filter = this._state.log_filter || 'all';

    // Update filter buttons
    var btns = document.querySelectorAll('#sp-log-filters .sp-log-filter-btn');
    for (var b = 0; b < btns.length; b++) {
      if (btns[b].getAttribute('data-level') === filter) btns[b].classList.add('active');
      else btns[b].classList.remove('active');
    }

    for (var i = 0; i < logs.length; i++) {
      var entry = logs[i];
      if (filter !== 'all' && entry.lvl !== filter) continue;
      this._appendLogEntry(el, entry);
    }
    el.scrollTop = el.scrollHeight;
  },

  _appendLogEntry: function(container, entry) {
    var div = document.createElement('div');
    div.className = 'log-' + entry.lvl;
    var d = new Date(entry.ts * 1000);
    var ts = ('0'+d.getHours()).slice(-2) + ':' + ('0'+d.getMinutes()).slice(-2) + ':' + ('0'+d.getSeconds()).slice(-2);
    div.textContent = ts + ' ' + entry.msg;
    container.appendChild(div);
  },

  /* ---- Incremental updates (no full re-render) ---- */
  pushLog: function(entry) {
    if (!this._state) return;
    this._state.logs.push(entry);
    if (this._state.logs.length > 200) this._state.logs = this._state.logs.slice(-200);
    var el = document.getElementById('sp-log');
    if (!el) return;
    var filter = this._state.log_filter || 'all';
    if (filter !== 'all' && entry.lvl !== filter) return;
    this._appendLogEntry(el, entry);
    el.scrollTop = el.scrollHeight;
  },

  pushTimer: function(id, label, endTs) {
    if (!this._state) this._state = {};
    if (!this._state.timers) this._state.timers = {};
    this._state.timers[id] = {label: label, end_ts: endTs};
    this._renderTimers();
  },

  pushDashboard: function(vid, vs) {
    if (!this._state) return;
    if (!this._state.village_statuses) this._state.village_statuses = {};
    this._state.village_statuses[vid] = vs;
    if (vid === this._state.active_village_id) this._renderDashboard();
    this._renderVillageList();
  },

  pushBotState: function(st) {
    if (this._state) this._state.bot_state = st;
    this._renderBotState(st);
  },

  _toggleFeature: function(feat) {
    if (!this._state) return;
    var ts = this._state.toggle_states || {};
    var newVal = !ts[feat];
    ts[feat] = newVal;
    this._state.toggle_states = ts;
    var btn = document.getElementById('sp-toggle-' + feat);
    if (btn) {
      btn.textContent = newVal ? 'ON' : 'OFF';
      btn.className = 'sp-onoff ' + (newVal ? 'on' : 'off');
    }
    console.log('STAEMME:toggle_' + feat + ':' + newVal);
  },

  /* ---- Build Queue ---- */
  _bqLabels: null,

  _initBqSelect: function() {
    var sel = document.getElementById('sp-bq-select');
    if (!sel || sel.options.length > 1) return;
    if (!this._bqLabels) return;
    sel.innerHTML = '';
    var keys = Object.keys(this._bqLabels);
    for (var i = 0; i < keys.length; i++) {
      var opt = document.createElement('option');
      opt.value = keys[i];
      opt.textContent = this._bqLabels[keys[i]];
      sel.appendChild(opt);
    }
    var self = this;
    sel.onchange = function() { self._bqAutoLevel(); };
    this._bqAutoLevel();
  },

  _bqAutoLevel: function() {
    var sel = document.getElementById('sp-bq-select');
    var inp = document.getElementById('sp-bq-level');
    if (!sel || !inp || !this._state) return;
    var vid = this._state.active_village_id;
    var levels = (this._state.building_levels || {})[vid] || {};
    var cur = levels[sel.value] || 0;
    inp.value = cur + 1;
  },

  _bqAdd: function() {
    var sel = document.getElementById('sp-bq-select');
    var inp = document.getElementById('sp-bq-level');
    if (!sel || !inp || !this._state) return;
    var vid = this._state.active_village_id;
    var building = sel.value;
    var level = parseInt(inp.value, 10);
    if (!building || !level || level < 1) return;
    console.log('STAEMME:bq_add:' + vid + ':' + building + ':' + level);
  },

  _renderBuildQueue: function() {
    var list = document.getElementById('sp-bq-list');
    if (!list || !this._state) return;
    list.innerHTML = '';
    var vid = this._state.active_village_id;
    var steps = (this._state.build_queues || {})[vid] || [];
    var levels = (this._state.building_levels || {})[vid] || {};
    var labels = this._bqLabels || {};

    if (steps.length === 0) {
      list.innerHTML = '<li class="sp-bq-empty">No build steps queued</li>';
      return;
    }

    for (var i = 0; i < steps.length; i++) {
      var s = steps[i];
      var cur = levels[s.building];
      var curStr = cur !== undefined ? cur : '?';
      var done = cur !== undefined && cur >= s.level;
      var label = labels[s.building] || s.building;

      var li = document.createElement('li');
      li.className = 'sp-bq-item' + (done ? ' completed' : '');
      li.innerHTML =
        '<span class="sp-bq-idx">' + (i+1) + '</span>' +
        (done ? '<span style="color:#4ecca3">&#10003;</span> ' : '') +
        '<span class="sp-bq-name">' + label + ' Lv ' + s.level + '</span>' +
        '<span class="sp-bq-cur">(cur: ' + curStr + ')</span>' +
        '<span class="sp-bq-actions">' +
          '<button onclick="console.log(\'STAEMME:bq_move:' + vid + ':' + i + ':up\')" title="Move up">&#9650;</button>' +
          '<button onclick="console.log(\'STAEMME:bq_move:' + vid + ':' + i + ':down\')" title="Move down">&#9660;</button>' +
          '<button onclick="console.log(\'STAEMME:bq_remove:' + vid + ':' + i + '\')" title="Remove">&#10005;</button>' +
        '</span>';
      list.appendChild(li);
    }
  },

  pushBuildQueue: function(vid, steps, levels) {
    if (!this._state) return;
    if (!this._state.build_queues) this._state.build_queues = {};
    if (!this._state.building_levels) this._state.building_levels = {};
    this._state.build_queues[vid] = steps;
    if (levels) this._state.building_levels[vid] = levels;
    if (vid === this._state.active_village_id) this._renderBuildQueue();
  },

  pushBotProtection: function(detected, pattern) {
    if (this._state) {
      this._state.bot_protection_detected = detected;
      this._state.bot_protection_pattern = pattern || '';
    }
    var banner = document.getElementById('sp-alert-banner');
    var text = document.getElementById('sp-alert-text');
    if (!banner) return;
    if (detected) {
      if (text) text.textContent = 'BOT PROTECTION: ' + (pattern || 'unknown');
      banner.classList.add('active');
    } else {
      banner.classList.remove('active');
    }
  }
};
"""


class SidePanel(PanelInterface):
    """Manages the injected side panel in the game page.

    JS->Python communication uses console.log('STAEMME:action') listened
    via page.on('console'). All state lives in PanelStateStore and is
    re-hydrated after every DOM reset (page navigation).
    """

    def __init__(self, browser: BrowserClient) -> None:
        super().__init__()
        self.browser = browser
        self._callbacks: dict[str, Callable[..., Coroutine]] = {}
        self._listener_attached = False
        self._inject_lock = asyncio.Lock()

    async def setup(self) -> None:
        """Initial setup: attach console listener, inject panel."""
        if not self._listener_attached:
            self.browser.page.on("console", self._on_console)
            self._listener_attached = True
        await self._inject()
        self.browser._panel_injector = self.reinject
        self.browser._attach_nav_listener()

    async def reinject(self) -> None:
        """Re-inject panel after a page navigation (DOM resets)."""
        await self._inject()

    async def _inject(self) -> None:
        """Inject CSS + HTML + JS, then hydrate from state.

        Uses a lock to prevent concurrent reinjects (load event vs
        _post_navigation race) from wiping hydrated state.
        """
        if self._inject_lock.locked():
            return  # another reinject is already running
        async with self._inject_lock:
            try:
                needs_full = not await self.browser.page.evaluate(
                    "!!(document.getElementById('staemme-panel')"
                    " && window.__sp && window.__sp._state)"
                )
                if needs_full:
                    await self._inject_css()
                    await self._inject_html()
                    await self._inject_js()
                await self._push_state()
            except Exception as e:
                log.warning("inject_failed", error=str(e))

    async def _inject_css(self) -> None:
        exists = await self.browser.page.evaluate(
            "!!document.querySelector('#staemme-panel-style')"
        )
        if not exists:
            await self.browser.page.add_style_tag(content=PANEL_CSS)
            await self.browser.page.evaluate("""
                (() => {
                    const styles = document.querySelectorAll('style');
                    const last = styles[styles.length - 1];
                    if (last) last.id = 'staemme-panel-style';
                })()
            """)

    async def _inject_html(self) -> None:
        exists = await self.browser.page.evaluate(
            "!!document.getElementById('staemme-panel')"
        )
        if not exists:
            escaped = PANEL_HTML.replace("`", "\\`").replace("${", "\\${")
            await self.browser.page.evaluate(f"""
                (() => {{
                    const div = document.createElement('div');
                    div.innerHTML = `{escaped}`;
                    document.body.appendChild(div.firstElementChild);
                }})()
            """)

    async def _inject_js(self) -> None:
        """Inject the __sp namespace JS and building labels."""
        await self.browser.page.evaluate(PANEL_JS)
        labels_json = json.dumps(BUILDING_LABELS, separators=(",", ":"))
        await self.browser.page.evaluate(
            f"window.__sp._bqLabels = {labels_json}"
        )

    async def _push_state(self) -> None:
        """Push full state blob to JS for hydration."""
        data = self.state.to_json_dict()
        data_json = json.dumps(data, separators=(",", ":"))
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.hydrate({data_json})"
        )

    # ------------------------------------------------------------------
    # Action handling
    # ------------------------------------------------------------------

    def on_action(self, action: str, callback: Callable[..., Coroutine]) -> None:
        self._callbacks[action] = callback

    def _on_console(self, msg) -> None:
        text = msg.text
        if not text.startswith(ACTION_PREFIX):
            return
        action_str = text[len(ACTION_PREFIX):]
        asyncio.ensure_future(self._handle_action(action_str))

    async def _handle_action(self, action_str: str) -> None:
        log.debug("panel_action", action=action_str)
        if ":" in action_str:
            action, value = action_str.split(":", 1)
        else:
            action, value = action_str, ""

        cb = self._callbacks.get(action)
        if cb:
            await cb(value)

    # ------------------------------------------------------------------
    # Status updates from Python -> JS (incremental)
    # ------------------------------------------------------------------

    async def update_status(
        self,
        state: str = "",
        village_name: str = "",
        coords: str = "",
        resources: dict[str, int] | None = None,
        population: str = "",
        incoming: int | None = None,
    ) -> None:
        """Backward-compatible status update. Updates state store and pushes."""
        if state:
            self.state.bot_state = state
            await self.browser.page.evaluate(
                f"window.__sp && window.__sp.pushBotState({json.dumps(state)})"
            )

    async def update_toggles(self, toggles: dict[str, bool]) -> None:
        """Sync toggle states from config to panel."""
        self.state.toggle_states.update(toggles)
        # Push via config render
        data = json.dumps(self.state.toggle_states, separators=(",", ":"))
        await self.browser.page.evaluate(f"""
            (() => {{
                if (!window.__sp || !window.__sp._state) return;
                window.__sp._state.toggle_states = {data};
                window.__sp._renderConfig();
            }})()
        """)

    async def update_troops_mode(self, mode: str, units: list[str] | None = None) -> None:
        if mode == "fill_scavenge":
            unit_str = ", ".join(units) if units else "spear"
            label = f"(fill: {unit_str})"
        elif mode == "targets":
            label = "(targets)"
        else:
            label = ""
        self.state.troops_mode_label = label
        safe = json.dumps(label)
        await self.browser.page.evaluate(f"""
            (() => {{
                if (window.__sp && window.__sp._state) window.__sp._state.troops_mode_label = {safe};
                var el = document.getElementById('sp-troops-mode');
                if (el) el.textContent = {safe};
            }})()
        """)

    async def add_log(self, message: str, level: str = "info") -> None:
        """Append a log entry — stored in state AND pushed incrementally."""
        entry = self.state.add_log(message, level)
        entry_json = json.dumps(
            {"ts": entry.timestamp, "msg": entry.message, "lvl": entry.level},
            separators=(",", ":"),
        )
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.pushLog({entry_json})"
        )

    async def update_timer(self, timer_id: str, label: str, end_ts: float) -> None:
        """Set or update a countdown timer."""
        self.state.set_timer(timer_id, label, end_ts)
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.pushTimer({json.dumps(timer_id)},{json.dumps(label)},{end_ts})"
        )

    async def update_build_queue(self, village_id: int) -> None:
        """Push the build queue + levels for a village to JS."""
        steps = self.state.build_queues.get(village_id, [])
        levels = self.state.building_levels.get(village_id, {})
        steps_json = json.dumps(steps, separators=(",", ":"))
        levels_json = json.dumps(levels, separators=(",", ":"))
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.pushBuildQueue({village_id},{steps_json},{levels_json})"
        )

    async def update_bot_protection(self, detected: bool, pattern: str = "") -> None:
        """Show or hide the bot protection alert banner."""
        self.state.bot_protection_detected = detected
        self.state.bot_protection_pattern = pattern
        detected_json = json.dumps(detected)
        pattern_json = json.dumps(pattern)
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.pushBotProtection({detected_json},{pattern_json})"
        )

    async def update_fill_unit(self, unit: str) -> None:
        """Push fill-scavenge training unit selection to UI."""
        self.state.fill_unit = unit
        unit_json = json.dumps(unit)
        await self.browser.page.evaluate(f"""
            (() => {{
                if (window.__sp && window.__sp._state) window.__sp._state.fill_unit = {unit_json};
                var fu = document.getElementById('sp-fill-unit');
                if (fu) fu.value = {unit_json};
            }})()
        """)

    async def update_village_status(self, vs: VillageStatus) -> None:
        """Push a village status update to dashboard."""
        self.state.set_village_status(vs)
        vs_dict = {
            "name": vs.name, "x": vs.x, "y": vs.y, "points": vs.points,
            "wood": vs.wood, "stone": vs.stone, "iron": vs.iron,
            "storage": vs.storage, "pop": vs.population, "pop_max": vs.max_population,
            "incoming": vs.incoming,
            "wood_rate": vs.wood_rate, "stone_rate": vs.stone_rate, "iron_rate": vs.iron_rate,
        }
        vs_json = json.dumps(vs_dict, separators=(",", ":"))
        await self.browser.page.evaluate(
            f"window.__sp && window.__sp.pushDashboard({vs.village_id},{vs_json})"
        )
