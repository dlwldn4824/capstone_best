// /check 의 브라우저 엔진(webapp/static/rppg2.js + vitals.js)이 tests/test_vitals.py 의 기준값을 그대로 내는지 본다.
// 두 파일은 전역(RPPG2 · VITALS)을 만드는 일반 스크립트라 vm 으로 한 번에 실행한다. /face 파이프라인과는 별개다.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const STATIC = fileURLToPath(new URL('../../static/', import.meta.url));
const src = ['rppg2.js', 'vitals.js'].map(f => readFileSync(STATIC + f, 'utf8')).join('\n;\n');
const { VITALS } = vm.runInNewContext(src + '\n;({ RPPG2, VITALS });', {}, { filename: 'legacy-vitals.js' });

// tests/test_vitals.py synth(): 심박 75 bpm(1.25 Hz) · 호흡 15회/분(0.25 Hz) 로 심박이 출렁이는(RSA) 얼굴 RGB
function synth(n = 900, fs = 30) {
  const w = 2 * Math.PI * 0.25, frames = [];
  for (let i = 0; i < n; i++) {
    const t = i / fs;
    const phi = 2 * Math.PI * 1.25 * (t - (0.06 / w) * Math.cos(w * t) + 0.06 / w);
    const p = Math.sin(phi) + 0.3 * Math.sin(2 * phi - 0.5);
    const amp = 1 + 0.15 * Math.sin(w * t);
    const d = 2 * Math.sin(2 * Math.PI * 0.05 * t);
    const b = Math.sin(w * t);
    frames.push({ t: t * 1000, rgb: [150 + 0.15 * amp * p + d + 0.3 * b, 110 + 0.5 * amp * p + d + 0.3 * b, 90 + 0.1 * amp * p + d + 0.3 * b] });
  }
  return frames;
}

describe('legacy vitals.js (/check) ↔ test_vitals.py', () => {
  const m = VITALS.analyze(synth());

  it('test_browser_vitals_match 기준값 (±0.15)', () => {
    const ref = { hr: 75.6, rmssd: 21.3, sdnn: 18.1, si: 682.6, stress: 87.3, rr: 14.8, beats: 38 };
    for (const [k, v] of Object.entries(ref)) expect(Math.abs(m[k] - v), `${k}=${m[k]}`).toBeLessThanOrEqual(0.15);
  });

  it('test_synthetic_heart_breath_and_hrv 조건', () => {
    expect(m.signal).toBe('high');
    expect(Math.abs(m.hr - 75)).toBeLessThan(1.5);
    expect(Math.abs(m.rr - 15)).toBeLessThanOrEqual(2);
    expect(m.rmssd).toBeGreaterThan(5);
    expect(m.irregular).toBe(false);
    expect(m.stress).toBeGreaterThanOrEqual(0);
    expect(m.stress).toBeLessThanOrEqual(100);
  });

  it('8초보다 짧으면 null', () => {
    expect(VITALS.analyze(synth(200))).toBeNull();
  });
});
