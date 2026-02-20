import { useState } from 'react';
import { api } from '../../hooks/useApi';
import { BUILDING_LABELS, type BuildStep } from '../../types';

interface Props {
  villageId: number;
  steps: BuildStep[];
  levels: Record<string, number>;
}

const BUILDING_IDS = Object.keys(BUILDING_LABELS);

export function BuildQueueEditor({ villageId, steps, levels }: Props) {
  const [selectedBuilding, setSelectedBuilding] = useState(BUILDING_IDS[0]);
  const [selectedLevel, setSelectedLevel] = useState(1);

  // Auto-level: set to current level + 1
  const handleBuildingChange = (building: string) => {
    setSelectedBuilding(building);
    const cur = levels[building] ?? 0;
    setSelectedLevel(cur + 1);
  };

  const handleAdd = async () => {
    if (selectedLevel < 1 || selectedLevel > 30) return;
    await api.addBuildStep(villageId, selectedBuilding, selectedLevel);
    // Auto-increment for next add
    setSelectedLevel((prev) => Math.min(30, prev + 1));
  };

  const handleRemove = async (index: number) => {
    await api.removeBuildStep(villageId, index);
  };

  return (
    <div>
      {/* Add row */}
      <div className="bq-add-row">
        <select
          value={selectedBuilding}
          onChange={(e) => handleBuildingChange(e.target.value)}
        >
          {BUILDING_IDS.map((id) => (
            <option key={id} value={id}>
              {BUILDING_LABELS[id]}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          max={30}
          value={selectedLevel}
          onChange={(e) => setSelectedLevel(Number(e.target.value))}
        />
        <button className="btn btn-start" onClick={handleAdd}>
          + Add
        </button>
      </div>

      {/* Queue list */}
      {steps.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)', fontSize: '11px', padding: '4px 0' }}>
          No build steps queued
        </div>
      ) : (
        <div className="bq-list">
          {steps.map((step, i) => {
            const curLevel = levels[step.building] ?? 0;
            const completed = curLevel >= step.level;
            return (
              <div key={i} className={`bq-item${completed ? ' completed' : ''}`}>
                <span className="bq-num">{i + 1}.</span>
                <span className="bq-name">{BUILDING_LABELS[step.building] ?? step.building}</span>
                <span className="bq-level">Lv {step.level}</span>
                <span className="bq-cur">(cur: {curLevel})</span>
                <div className="bq-actions">
                  <button onClick={() => handleRemove(i)} title="Remove">
                    x
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
