// 흔들림 보정(G2)과 빠른 측정(조기 종료) — scripts/experiments 결과를 회귀로 고정
import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze, liveEstimate, stableEnough, EARLY_STOP } from '../src/pipeline/index.js';

const cut = (s, t1) => s.filter(x => x.t <= t1 * 1000);

describe('G2: 창별 융합 + 실패 시 움직임 상쇄', () => {
  it('정지 상태: 융합만으로 통과, 움직임 상쇄는 쓰지 않는다', () => {
    for (const seed of [1, 2, 3]) {
      const r = analyze(synthSamples({ bpm: 72, seed }));
      expect(r.quality.pass).toBe(true);
      expect(r.method).toBe('fused');
      expect(Math.abs(r.bpm - 72)).toBeLessThan(1);
    }
  });
  it('심박 대역 끄덕임 20건: 통과한 것은 모두 ±2 bpm 안 (거짓 통과 0)', () => {
    let passed = 0;
    for (let seed = 1; seed <= 20; seed++) {
      const r = analyze(synthSamples({ bpm: 72, seed, nodHz: 1.25, nodShade: 0.01, nodPx: 6 }));
      if (r.quality.pass) { passed++; expect(Math.abs(r.bpm - 72)).toBeLessThanOrEqual(2); }
    }
    expect(passed).toBeGreaterThan(0);                  // 적어도 일부는 살린다 (예전엔 0)
  });
  it('맥박 없는 화면광은 움직임 상쇄 재시도로도 통과하지 않는다', () => {
    for (const seed of [1, 2, 3]) expect(analyze(synthSamples({ seed, pulseAmp: 0, screenHz: 1.3, screenAmp: 0.003 })).quality.pass).toBe(false);
  });
});

describe('빠른 측정: 조기 종료', () => {
  // 실시간처럼 1초마다 재고, 안정 + 전체 품질 통과면 멈춘다
  function simulate(samples) {
    const hist = [];
    for (let t = 6; t <= EARLY_STOP.maxSec; t++) {
      const s = cut(samples, t), live = liveEstimate(s);
      hist.push({ t, bpm: live.bpm, snrDb: live.snrDb });
      if (stableEnough(hist, t) && analyze(s, { resp: false }).quality.pass) return { t, r: analyze(s) };
    }
    return { t: EARLY_STOP.maxSec, r: analyze(samples) };
  }
  it('깨끗한 신호: 최소 시간(10초)에 끝나고 ±1 bpm 안', () => {
    for (const seed of [1, 2, 3]) {
      const { t, r } = simulate(synthSamples({ bpm: 75, seed, noise: 0.2 }));
      expect(t).toBe(EARLY_STOP.minSec);
      expect(Math.abs(r.bpm - 75)).toBeLessThanOrEqual(1);
    }
  });
  it('보통 잡음: 확신이 들 때까지 더 재고, 일찍 끝났다면 ±2 bpm 안', () => {
    for (const seed of [1, 2, 4, 5]) {
      const { t, r } = simulate(synthSamples({ bpm: 75, seed, noise: 0.6 }));
      if (t < EARLY_STOP.maxSec) expect(Math.abs(r.bpm - 75)).toBeLessThanOrEqual(2);
    }
  });
  it('맥박이 없으면 일찍 끝나지 않는다', () => {
    const { t } = simulate(synthSamples({ seed: 4, pulseAmp: 0, screenHz: 1.3, screenAmp: 0.003 }));
    expect(t).toBe(EARLY_STOP.maxSec);
  });
  it('stableEnough: 최소 시간 · 3개 · ±2 bpm · SNR 조건', () => {
    const h = [{ bpm: 70, snrDb: 5 }, { bpm: 71, snrDb: 5 }, { bpm: 70.5, snrDb: 5 }];
    expect(stableEnough(h, 9)).toBe(false);
    expect(stableEnough(h, 10)).toBe(true);
    expect(stableEnough([...h.slice(0, 2), { bpm: 74, snrDb: 5 }], 12)).toBe(false);
    expect(stableEnough([...h.slice(0, 2), { bpm: 70.5, snrDb: 1 }], 12)).toBe(false);
  });
});
