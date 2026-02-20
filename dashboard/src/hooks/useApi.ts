/** Thin REST helpers — all actions go through the API. */

const BASE = '/api';

async function post(path: string, body?: unknown) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

async function del(path: string) {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE' });
  return res.json();
}

export const api = {
  control: (action: 'start' | 'pause' | 'stop') => post(`/control/${action}`),

  toggleFeature: (feature: string, enabled: boolean) =>
    post(`/toggles/${feature}?enabled=${enabled}`),

  addBuildStep: (vid: number, building: string, level: number) =>
    post(`/build-queue/${vid}`, { building, level }),

  removeBuildStep: (vid: number, index: number) =>
    del(`/build-queue/${vid}/${index}`),

  setFarmThreshold: (value: number) => post(`/farm-threshold/${value}`),
};
