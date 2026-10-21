import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze, quickBpm } from '../src/pipeline/index.js';

const SEEDS = [1, 2, 3, 4, 5];

describe('견고성: 시간축·간섭·고조파·호흡', () => {
  it('얼굴 놓침 2×1.5s → 재표본화 후 bpm ±1.5 이내 이거나 coverage 로 실패', () => {
    for (const seed of SEEDS) {
      const r = analyze(synthSamples({ bpm: 72, seed, gaps: [[8, 1.5], [19, 1.5]] }));
      const ok = Math.abs(r.bpm - 72) <= 1.5 || (!r.quality.pass && r.quality.reason === 'coverage');
      expect(ok).toBe(true);
      expect(Math.abs(r.bpm - 72)).toBeLessThan(1.5);   // 재표본화로 실제로 맞춘다 (예전: 약 -6 bpm)
      expect(r.coverage.maxGapSec).toBeGreaterThan(1.4);
      expect(r.quality.coverageOk).toBe(false);
    }
  });
  it('프레임 20% 드롭 + 24fps 에도 bpm ±1.5 (fs 추정이 아니라 타임스탬프 기준)', () => {
    for (const seed of SEEDS) {
      const s = synthSamples({ bpm: 80, fs: 24, seed }).filter((_, i) => (i * 7919 + seed) % 5 !== 0);
      const r = analyze(s);
      expect(Math.abs(r.bpm - 80)).toBeLessThan(1.5);
      expect(r.fsEstimated).toBeLessThan(20);
    }
  });
  it('맥박 없이 화면광만 (1.3Hz) → 품질 실패', () => {
    for (const seed of SEEDS) {
      const r = analyze(synthSamples({ seed, pulseAmp: 0, screenHz: 1.3, screenAmp: 0.003 }));
      expect(r.quality.pass).toBe(false);
    }
  });
  it('심박 대역 끄덕임 (1.25Hz, 6px) → 움직임 상쇄로 맞게 살리거나, interference 로 실패. 틀린 값 통과는 없다', () => {
    for (const seed of SEEDS) {
      const r = analyze(synthSamples({ bpm: 72, seed, nodHz: 1.25, nodShade: 0.01, nodPx: 6 }));
      if (r.quality.pass) {
        expect(r.method).toBe('fused+motion');          // 기본 융합은 실패하고 움직임 상쇄 재시도로 통과
        expect(Math.abs(r.bpm - 72)).toBeLessThanOrEqual(2);
      } else {
        expect(r.quality.reason).toBe('interference');
        expect(r.quality.interferenceOk).toBe(false);
      }
    }
  });
  it('호흡 성분 없음 → resp.rate NaN, 호흡 있음 → 15회/분 근처', () => {
    for (const seed of SEEDS) {
      const none = analyze(synthSamples({ bpm: 72, seed, respAmp: 0, respHeadPx: 0 }));
      expect(Number.isNaN(none.resp.rate)).toBe(true);
      expect(none.resp.agree).toBe(false);
    }
    const yes = analyze(synthSamples({ bpm: 72, seed: 1 }));
    expect(Math.abs(yes.resp.rate - 15)).toBeLessThan(2);
    expect(yes.resp.agree).toBe(true);
  });
  it('45 bpm + 2차 고조파가 기본파만큼 강함 → ±2 bpm (2배로 잠기지 않음)', () => {
    for (const seed of SEEDS) {
      const r = analyze(synthSamples({ bpm: 45, seed, h2: 1.0 }));
      expect(Math.abs(r.bpm - 45)).toBeLessThan(2);
    }
  });
  it('빠른 심박(110 bpm)은 절반으로 잘못 내려가지 않음', () => {
    for (const seed of SEEDS) expect(Math.abs(analyze(synthSamples({ bpm: 110, seed })).bpm - 110)).toBeLessThan(2);
  });
  it('HRV 신뢰 플래그: 잡음 큰 신호(SNR<10)는 hrvReliable=false, 깨끗하면 true', () => {
    const noisy = analyze(synthSamples({ bpm: 72, seed: 4, noise: 0.6 }));
    expect(noisy.snrDb).toBeLessThan(10);
    expect(noisy.hrvReliable).toBe(false);
    const clean = analyze(synthSamples({ bpm: 72, seed: 1, noise: 0.05, pulseAmp: 2 }));
    expect(clean.snrDb).toBeGreaterThanOrEqual(10);
    expect(clean.hrvPairs).toBeGreaterThanOrEqual(20);
    expect(clean.hrvReliable).toBe(true);
  });
  it('quickBpm: 유효 10초 전엔 NaN, 창 안에 얼굴 놓침이 있으면 NaN', () => {
    expect(Number.isNaN(quickBpm(synthSamples({ bpm: 66, durationSec: 8 })).bpm)).toBe(true);
    expect(Math.abs(quickBpm(synthSamples({ bpm: 66, durationSec: 11 })).bpm - 66)).toBeLessThan(2);
    expect(Number.isNaN(quickBpm(synthSamples({ bpm: 66, durationSec: 14, gaps: [[10, 2]] })).bpm)).toBe(true);   // 허용 1.5초보다 긴 놓침
  });
});
