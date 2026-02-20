import { useState } from 'react';
import { api } from '../../hooks/useApi';

interface Props {
  threshold: number;
}

export function FarmThreshold({ threshold }: Props) {
  const [value, setValue] = useState(threshold);

  const handleChange = async (newVal: number) => {
    if (newVal < 1 || newVal > 100) return;
    setValue(newVal);
    await api.setFarmThreshold(newVal);
  };

  return (
    <div className="threshold-row">
      <label>LC Threshold</label>
      <input
        type="number"
        min={1}
        max={100}
        value={value}
        onChange={(e) => handleChange(Number(e.target.value))}
      />
      <span style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
        max LC per attack before Template A
      </span>
    </div>
  );
}
