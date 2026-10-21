// 독립 검증(2026-10-21)에서 확정된 결함의 회귀 테스트
import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze } from '../src/pipeline/index.js';
import { faceState } from '../src/pipeline/face.js';
import { resultView } from '../src/ui/view.js';

const frame = (t, blink = 0) => ({ t, blink, mouthOpen: 0, faceCenter: [320, 240], faceWidth: 200, brightness: 140 });
const blinkAt = t => ((t / 1000) % 4 < 0.15 ? 0.9 : 0);   // 4초마다 깜빡임 = 분당 15회

describe('검증 결함 회귀', () => {
  it('얼굴을 놓친 2초가 눈 감긴 시간 · 하품으로 잡히지 않는다', () => {
    const s = [];
    for (let t = 0; t < 30000; t += 33) { if (t > 10000 && t < 12000) continue; s.push(frame(t, t >= 12000 && t < 12040 ? 0.9 : blinkAt(t))); }
    const f = faceState(s);
    expect(f.eyeClosedRatio).toBeLessThan(0.06);          // 결함 시 0.068 이상
    expect(f.durationSec).toBeLessThan(28.5);              // 놓친 2초 제외
    expect(f.yawns).toBe(0);
  });
  it('깜빡임 빈도는 얼굴이 잡힌 시간으로 나눈다', () => {
    const s = [];
    for (let t = 0; t < 30000; t += 33) { if (t > 3000 && t < 27000) continue; s.push(frame(t, blinkAt(t))); }
    const f = faceState(s);
    expect(f.durationSec).toBeLessThan(7);
    expect(f.blinkPerMin).toBeGreaterThan(12);              // 결함 시 4.0
    const v = resultView({ r: analyze(synthSamples({ seed: 1 })), f });
    expect(v.tiles.find(t => t.key === 'blink').state).toBe('held');   // 20초 미만이면 보류
  });
  it('호흡 상세에 쓰는 head · light 주기가 결과에 있다', () => {
    const r = analyze(synthSamples({ seed: 1, respHeadPx: 2, noise: 0.1 }));
    expect(r.resp).toHaveProperty('head');
    expect(r.resp).toHaveProperty('light');
    expect(Number.isFinite(r.resp.head)).toBe(true);
  });
  it('30초 중 얼굴이 6초만 잡히면 이유는 짧음이 아니라 얼굴 놓침, 품질 표는 지어낸 비율을 보여 주지 않는다', () => {
    const s = synthSamples({ seed: 2 }).filter(x => x.t < 3000 || x.t > 27000);
    const r = analyze(s);
    expect(r.quality.reason).toBe('coverage');
    const v = resultView({ r, f: faceState(s) });
    expect(v.status).toBe('retry');
    expect(v.quality).toHaveLength(1);
    expect(v.quality[0].label).toBe('얼굴이 잡힌 시간');
  });
  it('다시 재기 상태의 심박은 단위 없이 – ', () => {
    const v = resultView({ r: analyze(synthSamples({ brightness: 40 })), f: null });
    expect(v.hr.value).toBe('–');
    expect(v.hr.unit).toBe('');
  });
});
