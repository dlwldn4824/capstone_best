// 결과 화면 규칙: 실제 analyze() · faceState() 결과로 무엇이 보이는지 확인한다.
import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze } from '../src/pipeline/index.js';
import { faceState } from '../src/pipeline/face.js';
import { resultView } from '../src/ui/view.js';

const scanOf = samples => ({ r: analyze(samples), f: faceState(samples) });
const tile = (v, k) => v.tiles.find(t => t.key === k);
// 사람처럼 3–5초마다 0.15초 깜빡임
function withBlinks(samples, everySec = 4) {
  for (const s of samples) s.blink = (s.t / 1000) % everySec < 0.15 ? 0.9 : 0;
  return samples;
}

describe('결과 화면 규칙', () => {
  it('얼굴이 없으면 noface, 숫자 없음', () => {
    const v = resultView({ r: null, f: null });
    expect(v.status).toBe('noface');
    expect(v.tiles).toHaveLength(0);
  });

  it('깨끗한 신호: 심박 표시(±1 bpm), 맥파, 신호 좋음, 박동 간격 참고, 깜빡임 횟수가 실제와 맞음', () => {
    const s = withBlinks(synthSamples({ bpm: 72, seed: 1, noise: 0.05, pulseAmp: 2, rrJitterMs: 30, blinkRate: 0 }));
    const v = resultView(scanOf(s));
    expect(v.status).toBe('ok');
    expect(Math.abs(Number(v.hr.value) - 72)).toBeLessThanOrEqual(1);
    expect(v.wave).toBe(true);
    expect(v.signal.label).toBe('신호 좋음');
    expect(tile(v, 'hrv').state).toBe('ref');
    expect(Number(tile(v, 'hrv').value)).toBeGreaterThan(0);
    expect(tile(v, 'blink').state).toBe('ok');
    expect(Number(tile(v, 'blink').value)).toBeGreaterThanOrEqual(13);   // 4초마다 → 분당 15회
    expect(Number(tile(v, 'blink').value)).toBeLessThanOrEqual(17);
    expect(tile(v, 'head').state).toBe('ok');
  });

  it('보통 신호(기본 잡음): 심박은 보이지만 박동 간격은 보류', () => {
    for (const seed of [1, 2, 3]) {
      const r = analyze(synthSamples({ bpm: 80, seed, noise: 0.6 }));
      const v = resultView({ r, f: null });
      if (v.status !== 'ok') continue;
      expect(Math.abs(Number(v.hr.value) - 80)).toBeLessThanOrEqual(1);
      if (r.snrDb < 10) {
        expect(v.signal.label).toBe('신호 보통');
        expect(tile(v, 'hrv').state).toBe('held');
        expect(tile(v, 'hrv').value).toBe('–');
      }
    }
  });

  it('얼굴 놓침 2초: 다시 재기, 심박 · 박동 간격 · 호흡은 – , 이유는 얼굴', () => {
    const s = synthSamples({ bpm: 72, seed: 2, gaps: [[10, 2]] });
    const v = resultView(scanOf(s));
    expect(v.status).toBe('retry');
    expect(v.message).toContain('얼굴');
    expect(v.hr.value).toBe('–');
    expect(v.wave).toBe(false);
    expect(tile(v, 'hrv').value).toBe('–');
    expect(tile(v, 'resp').value).toBe('–');
    expect(v.quality.find(q => q.label === '얼굴이 잡힌 시간').ok).toBe(false);
  });

  it('맥박 없이 화면 깜빡임만: 숫자를 보여 주지 않는다', () => {
    for (const seed of [1, 2, 3]) {
      const v = resultView(scanOf(synthSamples({ seed, pulseAmp: 0, screenHz: 1.3, screenAmp: 0.003 })));
      expect(v.status).toBe('retry');
      expect(v.hr.value).toBe('–');
    }
  });

  it('심박 대역 끄덕임: 다시 재기, 이유 문구가 비어 있지 않음', () => {
    const v = resultView(scanOf(synthSamples({ bpm: 70, seed: 3, nodHz: 1.25, nodShade: 0.01, nodPx: 6 })));
    expect(v.status).toBe('retry');
    expect(v.message.length).toBeGreaterThan(5);
  });

  it('호흡 성분 없음: 호흡 타일은 보류', () => {
    const v = resultView(scanOf(synthSamples({ bpm: 72, seed: 4, respAmp: 0, respHeadPx: 0, noise: 0.1 })));
    expect(tile(v, 'resp').state).toBe('held');
    expect(tile(v, 'resp').value).toBe('–');
  });

  it('호흡 15회/분이 뚜렷하면 참고로 표시하고 ±2회/분 안', () => {
    let shown = 0;
    for (const seed of [1, 2, 3, 4, 5]) {
      const v = resultView(scanOf(synthSamples({ bpm: 72, seed, respHeadPx: 2, noise: 0.1 })));
      const t = tile(v, 'resp');
      if (t.state === 'ref') { shown++; expect(Math.abs(Number(t.value) - 15)).toBeLessThanOrEqual(2); }
    }
    expect(shown).toBeGreaterThanOrEqual(3);
  });

  it('어두운 얼굴: 다시 재기, 밝기 이유', () => {
    const v = resultView(scanOf(synthSamples({ brightness: 40 })));
    expect(v.status).toBe('retry');
    expect(v.message).toContain('밝');
  });

  it('20초 미만 얼굴 기록이면 깜빡임은 보류', () => {
    const v = resultView(scanOf(synthSamples({ durationSec: 15 })));
    expect(tile(v, 'blink').state).toBe('held');
  });

  it('어떤 시나리오든 화면 값에 NaN · undefined · Infinity 문자열이 없다', () => {
    const cases = [
      synthSamples({ seed: 9 }), synthSamples({ noise: 30, seed: 9 }), synthSamples({ durationSec: 9 }),
      synthSamples({ gaps: [[5, 3], [15, 3]] }), synthSamples({ bpm: 45, h2: 1 }), synthSamples({ bpm: 150 }),
    ];
    for (const s of cases) {
      const v = resultView(scanOf(s));
      const text = JSON.stringify(v);
      expect(text).not.toMatch(/NaN|undefined|Infinity/);
    }
  });
});
