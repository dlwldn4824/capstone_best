import { describe, it, expect } from 'vitest';
import { hrvFromRR } from '../src/pipeline/hrv.js';
import { synthSamples } from '../src/debug/synth.js';
import { analyze } from '../src/pipeline/index.js';

describe('HRV 지표', () => {
  it('알려진 RR 배열의 RMSSD/SDNN/pNN50', () => {
    const rr = [800, 850, 790, 900, 820, 880, 810, 870];
    const h = hrvFromRR(rr);
    // 수기 계산값
    expect(h.rmssd).toBeCloseTo(72.8, 0);
    expect(h.sdnn).toBeCloseTo(40.4, 0);
    expect(h.pnn50).toBeCloseTo(85.7, 0);
    expect(h.baevskySI).toBeGreaterThan(0);
  });
  it('일정한 RR이면 RMSSD ≈ 0, SI 큼', () => {
    const h = hrvFromRR(new Array(30).fill(830));
    expect(h.rmssd).toBe(0);
    expect(h.baevskySI).toBeGreaterThan(100);
  });
  it('합성 맥파에서 RR 개수가 박동 수와 맞음 (72bpm × 30s ≈ 36)', () => {
    const r = analyze(synthSamples({ bpm: 72, seed: 4 }));
    expect(r.rr.length).toBeGreaterThanOrEqual(30);
    expect(r.rr.length).toBeLessThanOrEqual(37);
    expect(Math.abs(r.meanRR - 833)).toBeLessThan(15);
  });
  it('신호가 깨끗할 때(SNR>10dB) RR 지터 40ms → RMSSD 40~70ms, 지터 0 → 30ms 미만', () => {
    for (const seed of [1, 2, 3]) {
      const a = analyze(synthSamples({ bpm: 72, seed, rrJitterMs: 0, noise: 0.1 }));
      const b = analyze(synthSamples({ bpm: 72, seed, rrJitterMs: 40, noise: 0.1 }));
      expect(a.rmssd).toBeLessThan(30);
      expect(b.rmssd).toBeGreaterThan(40);
      expect(b.rmssd).toBeLessThan(70);
      expect(b.rmssd).toBeGreaterThan(a.rmssd);
    }
  });
  it('잡음이 크면(SNR<8dB) RMSSD는 신뢰할 수 없음을 기록 (문서화용)', () => {
    const r = analyze(synthSamples({ bpm: 72, seed: 4, noise: 0.6 }));
    expect(r.snrDb).toBeLessThan(10);
  });
});
