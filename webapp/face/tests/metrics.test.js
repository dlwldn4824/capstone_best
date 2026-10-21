import { describe, it, expect } from 'vitest';
import { toMetrics, stressScore, stressZone, signalOf, SI_LO, SI_HI } from '../src/pipeline/metrics.js';

const base = {
  bpm: 72, snrDb: 12, rmssd: 38, sdnn: 55, pnn50: 12, baevskySI: 224,
  hrvReliable: true, resp: { rate: 15, agree: true }, quality: { pass: true },
};

describe('check 로 보내는 metrics', () => {
  it('스트레스 지수는 vitals.js 와 같은 축이다 (SI 50→0, 1000→100)', () => {
    expect(stressScore(SI_LO)).toBe(0);
    expect(stressScore(SI_HI)).toBe(100);
    expect(stressScore(224)).toBeGreaterThan(45);
    expect(stressScore(224)).toBeLessThan(55);
    expect(stressScore(null)).toBe(null);
    expect(stressScore(0)).toBe(null);
  });

  it('구간 이름도 같다', () => {
    expect(stressZone(20)).toBe('편안');
    expect(stressZone(45)).toBe('보통');
    expect(stressZone(70)).toBe('높음');
    expect(stressZone(90)).toBe('매우 높음');
  });

  it('신호 등급은 3 dB · 0 dB 로 가른다', () => {
    expect(signalOf(5, true)).toBe('high');
    expect(signalOf(1, true)).toBe('mid');
    expect(signalOf(-1, true)).toBe('low');
    expect(signalOf(12, false)).toBe('low');     // 품질에 떨어지면 등급을 주지 않는다
  });

  it('품질을 통과하면 심박과 HRV 를 모두 보낸다', () => {
    const m = toMetrics(base);
    expect(m.hr).toBe(72);
    expect(m.rmssd).toBe(38);
    expect(m.si).toBe(224);
    expect(m.hrv_conf).toBe('high');
    expect(m.rr).toBe(15);
    expect(m.signal).toBe('high');
  });

  it('품질에 떨어지면 심박을 보내지 않는다', () => {
    const m = toMetrics({ ...base, quality: { pass: false } });
    expect(m.hr).toBe(null);
    expect(m.rmssd).toBe(null);
    expect(m.stress).toBe(null);
    expect(m.signal).toBe('low');
  });

  it('HRV 문턱 아래면 박동 간격 쪽만 빼고 심박은 보낸다', () => {
    const m = toMetrics({ ...base, hrvReliable: false });
    expect(m.hr).toBe(72);
    expect(m.rmssd).toBe(null);
    expect(m.sdnn).toBe(null);
    expect(m.si).toBe(null);
    expect(m.stress).toBe(null);
    expect(m.hrv_conf).toBe('low');
  });

  it('호흡은 두 주기가 맞을 때만 보낸다', () => {
    expect(toMetrics({ ...base, resp: { rate: 15, agree: false } }).rr).toBe(null);
    expect(toMetrics({ ...base, resp: { rate: 15, agree: false } }).rr_conf).toBe('low');
  });

  it('없는 값을 지어내지 않는다 (irregular)', () => {
    expect(toMetrics(base).irregular).toBe(null);
  });

  it('check.py 의 METRIC_KEYS 를 모두 채운다', () => {
    const keys = ['hr', 'snr', 'signal', 'rmssd', 'sdnn', 'pnn50', 'si', 'stress', 'hrv_conf', 'irregular', 'rr', 'rr_conf'];
    expect(Object.keys(toMetrics(base)).sort()).toEqual([...keys].sort());
  });
});
