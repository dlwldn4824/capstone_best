import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze, quickBpm } from '../src/pipeline/index.js';

describe('POS + FFT bpm (합성 신호)', () => {
  for (const bpm of [55, 72, 95, 120]) {
    for (const seed of [1, 2, 3]) {
      it(`bpm=${bpm} seed=${seed} → 오차 1 bpm 이내`, () => {
        const r = analyze(synthSamples({ bpm, seed }));
        expect(Math.abs(r.bpm - bpm)).toBeLessThan(1.0);
        expect(r.snrDb).toBeGreaterThan(0);
        expect(r.quality.pass).toBe(true);
      });
    }
  }
  it('조명 드리프트 2배(±8%)에도 피크 유지', () => {
    const r = analyze(synthSamples({ bpm: 80, driftAmp: 0.08, seed: 7 }));
    expect(Math.abs(r.bpm - 80)).toBeLessThan(1.0);
  });
  it('quickBpm 10초 창', () => {
    const r = quickBpm(synthSamples({ bpm: 66, durationSec: 12 }));
    expect(Math.abs(r.bpm - 66)).toBeLessThan(2.0);
  });
  it('fs 추정: 25fps 입력도 처리', () => {
    const r = analyze(synthSamples({ bpm: 70, fs: 25 }));
    expect(Math.abs(r.fsEstimated - 25)).toBeLessThan(0.5);
    expect(Math.abs(r.bpm - 70)).toBeLessThan(1.0);
  });
});
