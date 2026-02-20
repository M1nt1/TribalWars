import { useState } from 'react';
import { DashboardTab } from './components/Dashboard/DashboardTab';
import { ConfigTab } from './components/Config/ConfigTab';
import { LogTab } from './components/Log/LogTab';
import { VNCBanner } from './components/VNCBanner';
import { useWebSocket } from './hooks/useWebSocket';
import { api } from './hooks/useApi';

type Tab = 'dashboard' | 'config' | 'log';

export default function App() {
  const { state, connected, sendAction } = useWebSocket();
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');

  const handleSelectVillage = (vid: number) => {
    sendAction('select_village', String(vid));
  };

  return (
    <>
      {/* Header */}
      <header className="app-header">
        <div className={`status-dot ${state.bot_state}`} />
        <span className="status-label">{state.bot_state}</span>
        <h1>Staemme Bot</h1>
        <span className={`connection-badge ${connected ? 'online' : 'offline'}`}>
          {connected ? 'LIVE' : 'OFFLINE'}
        </span>
        <div className="header-controls">
          <button className="btn btn-start" onClick={() => api.control('start')}>
            Start
          </button>
          <button className="btn btn-pause" onClick={() => api.control('pause')}>
            Pause
          </button>
          <button className="btn btn-stop" onClick={() => api.control('stop')}>
            Stop
          </button>
        </div>
      </header>

      {/* VNC login banner */}
      <VNCBanner botState={state.bot_state} />

      {/* Tab bar */}
      <nav className="tab-bar">
        {(['dashboard', 'config', 'log'] as Tab[]).map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? 'active' : ''}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </nav>

      {/* Tab content */}
      {activeTab === 'dashboard' && (
        <DashboardTab state={state} onSelectVillage={handleSelectVillage} />
      )}
      {activeTab === 'config' && (
        <ConfigTab state={state} sendAction={sendAction} />
      )}
      {activeTab === 'log' && <LogTab logs={state.logs} />}
    </>
  );
}
