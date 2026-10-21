import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze, WINDOW } from '../src/pipeline/index.js';

// 측정 중간에만 머리를 흔든 스캔. [t0, t1] 초 구간의 얼굴 중심만 크게 흔든다.
function shakeBetween(samples, t0, t1, px = 14) {
  let k = 0;
  return samples.map(s => {
    const t = s.t / 1000;
    if (t < t0 || t > t1) return s;
    k++;
    const j = (a) => px * Math.sin(a * k * 2.4) + px * 0.6 * Math.sin(a * k * 7.1);
    return { ...s, faceCenter: [s.faceCenter[0] + j(1), s.faceCenter[1] + j(1.7)] };
  });
}

describe('구간 선택: 흔들린 구간을 빼고 깨끗한 구간만 쓴다', () => {
  it('처음부터 끝까지 깨끗하면 전체를 쓴다 (구간 선택 안 함)', () => {
    const r = analyze(synthSamples({ bpm: 72, seed: 3 }));
    expect(r.quality.pass).toBe(true);
    expect(r.window).toBe(null);
    expect(r.method).not.toContain('window');
  });

  it('앞 8초만 흔들린 스캔: 뒤쪽 구간으로 살리고 bpm 이 맞는다', () => {
    const s = shakeBetween(synthSamples({ bpm: 78, seed: 5 }), 0, 8);
    expect(analyze(s, { windowRetry: false }).quality.pass).toBe(false);   // 전체로 보면 떨어진다
    const r = analyze(s);
    expect(r.quality.pass).toBe(true);
    expect(r.window).not.toBe(null);
    expect(r.window.startSec).toBeGreaterThanOrEqual(5);                   // 흔들린 앞부분을 피했다
    expect(Math.abs(r.bpm - 78)).toBeLessThanOrEqual(5);
    expect(r.method).toContain('window');
  });

  it('고른 구간은 15초라 박동 간격은 보류한다', () => {
    const s = shakeBetween(synthSamples({ bpm: 78, seed: 5, rrJitterMs: 30 }), 0, 8);
    const r = analyze(s);
    if (r.window) {
      expect(r.durationSec).toBeLessThanOrEqual(WINDOW.sec + 1);
      expect(r.hrvReliable).toBe(false);
    }
  });

  it('맥박이 없으면 구간을 골라도 통과하지 않는다', () => {
    for (const seed of [1, 2, 3]) {
      const r = analyze(synthSamples({ seed, pulseAmp: 0, screenHz: 1.3, screenAmp: 0.003 }));
      expect(r.quality.pass).toBe(false);
    }
  });

  it('처음부터 끝까지 흔들리면 고를 구간이 없다', () => {
    const s = shakeBetween(synthSamples({ bpm: 72, seed: 7 }), 0, 30);
    const r = analyze(s);
    expect(r.quality.pass).toBe(false);
    expect(r.window).toBe(null);
  });

  it('구간보다 짧은 스캔에서는 구간 선택을 하지 않는다', () => {
    const r = analyze(synthSamples({ bpm: 72, seed: 3, durationSec: 12, noise: 40 }));
    expect(r.window).toBe(null);
  });
});
