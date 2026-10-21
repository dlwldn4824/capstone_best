import { describe, it, expect } from 'vitest';
import { baselineOf, deviationOf, unexplained, BASELINE } from '../src/pipeline/baseline.js';

const scan = (bpm, { pass = true, ts = Date.now(), why = null } = {}) => ({ ts, why, r: { bpm, quality: { pass } } });

describe('평소값', () => {
  it('측정이 모자라면 평소를 말하지 않는다', () => {
    const b = baselineOf([scan(70), scan(72)]);
    expect(b.ready).toBe(false);
    expect(b.need).toBe(BASELINE.minScans - 2);
  });

  it('품질을 통과한 것만 센다', () => {
    const scans = [scan(70), scan(71), scan(72), scan(73), scan(200, { pass: false })];
    const b = baselineOf(scans);
    expect(b.ready).toBe(false);          // 통과분이 4개뿐
    expect(b.n).toBe(4);
  });

  it('한 번 크게 튄 값에 평소가 끌려가지 않는다', () => {
    const b = baselineOf([scan(70), scan(71), scan(72), scan(73), scan(74), scan(160)]);
    expect(b.ready).toBe(true);
    expect(Math.abs(b.bpm - 72)).toBeLessThanOrEqual(2);
  });
});

describe('평소와 다른가', () => {
  const base = baselineOf([scan(70), scan(71), scan(72), scan(73), scan(74)]);

  it('측정 오차 안의 차이는 평소와 같다고 본다', () => {
    expect(deviationOf(base.bpm + 3, base).level).toBe('same');
  });

  it('뚜렷하게 높으면 high', () => {
    const d = deviationOf(base.bpm + 14, base);
    expect(d.level).toBe('high');
    expect(d.diff).toBeCloseTo(14, 5);
  });

  it('뚜렷하게 낮으면 low', () => {
    expect(deviationOf(base.bpm - 14, base).level).toBe('low');
  });

  it('평소를 모르면 unknown', () => {
    expect(deviationOf(80, baselineOf([scan(70)])).level).toBe('unknown');
  });

  it('흩어짐이 큰 사람은 기준도 넓어진다', () => {
    const wide = baselineOf([scan(60), scan(70), scan(80), scan(90), scan(100)]);
    expect(deviationOf(wide.bpm + 8, wide).level).toBe('same');
  });
});

describe('설명되지 않은 변화만 쌓기', () => {
  const day = n => Date.now() - n * 86400000;
  const base = [scan(70, { ts: day(9) }), scan(71, { ts: day(8) }), scan(72, { ts: day(7) }), scan(73, { ts: day(6) }), scan(74, { ts: day(5) })];

  it('이유를 댄 날은 쌓이지 않는다', () => {
    const u = unexplained([...base, scan(95, { ts: day(1), why: 'exercise' })]);
    expect(u.streak).toBe(0);
  });

  it('짚이는 게 없는 날만 이어서 센다', () => {
    const u = unexplained([...base, scan(95, { ts: day(2), why: 'none' }), scan(96, { ts: day(1), why: 'none' })]);
    expect(u.streak).toBe(2);
  });

  it('평소와 같은 날은 이유가 none 이어도 쌓이지 않는다', () => {
    const u = unexplained([...base, scan(72, { ts: day(1), why: 'none' })]);
    expect(u.streak).toBe(0);
  });
});
