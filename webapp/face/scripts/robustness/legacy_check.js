// Frozen copy of the scoring rules that lived in src/logic/check.js at audit time (that file was removed upstream).
// Used only so the audit tables (06/07/08/09) stay reproducible.
import { respFromSamples } from '../../src/pipeline/resp.js';
export const SI_LO = 50, SI_HI = 1000;
export const WEIGHTS = { stress: 0.35, hrv: 0.2, hr: 0.15, rr: 0, life: 0.3 };
const r1 = v => (v == null || !Number.isFinite(v) ? null : Math.round(v * 10) / 10);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export function stressScore(si) {
  if (si == null || !Number.isFinite(si) || si <= 0) return null;
  return r1(clamp((Math.log(si) - Math.log(SI_LO)) / (Math.log(SI_HI) - Math.log(SI_LO)), 0, 1) * 100);
}
export const stressZone = s => (s == null ? null : s < 30 ? '편안' : s < 60 ? '보통' : s < 80 ? '높음' : '매우 높음');
export function irregularOf(rr) {
  if (!rr || rr.length < 9) return null;
  const mean = rr.reduce((a, b) => a + b, 0) / rr.length;
  let big = 0; for (let i = 1; i < rr.length; i++) if (Math.abs(rr[i] - rr[i - 1]) > 0.2 * mean) big++;
  return big / (rr.length - 1) > 0.3;
}
export function toMetrics(result, samples) {
  const snr = result.snrDb;
  const signal = snr >= 10 ? 'high' : snr >= 0 ? 'mid' : 'low';
  const hrvConf = signal === 'low' || result.rr.length < 8 || !Number.isFinite(result.rmssd) ? 'low' : signal === 'high' ? 'high' : 'mid';
  const okHrv = hrvConf !== 'low';
  const resp = respFromSamples(samples, result.fsEstimated);
  const respOk = signal !== 'low' && Number.isFinite(resp.rate) && resp.snrDb >= 0;
  return {
    hr: r1(result.bpm), snr: r1(snr), signal,
    rmssd: okHrv ? r1(result.rmssd) : null, si: okHrv ? r1(result.baevskySI) : null, stress: okHrv ? stressScore(result.baevskySI) : null, hrv_conf: hrvConf,
    irregular: signal === 'high' ? irregularOf(result.rr) : null,
    rr: respOk ? r1(resp.rate) : null, rr_conf: respOk ? (resp.snrDb >= 3 ? 'mid' : 'low') : 'low',
  };
}
function bandScore(v, lo, hi, per) { if (v == null) return null; const d = v < lo ? lo - v : v > hi ? v - hi : 0; return Math.max(0, 100 - per * d); }
function lifeScore(sleepH, caffeine, mood) {
  const p = []; if (sleepH != null) p.push(bandScore(sleepH, 7, 9, 15)); if (caffeine != null) p.push(Math.max(0, 100 - 20 * Math.max(0, caffeine - 1))); if (mood != null) p.push(20 * mood);
  return p.length ? p.reduce((a, b) => a + b, 0) / p.length : null;
}
export function healthScore(m, sleepH = null, caffeine = null, mood = null) {
  const comp = {
    stress: m.stress == null ? null : 100 - m.stress,
    hrv: !m.rmssd ? null : clamp((Math.log(m.rmssd) - Math.log(10)) / (Math.log(80) - Math.log(10)) * 100, 0, 100),
    hr: bandScore(m.signal !== 'low' ? m.hr : null, 55, 85, 2.5), rr: bandScore(m.rr, 12, 20, 8), life: lifeScore(sleepH, caffeine, mood),
  };
  const have = Object.entries(comp).filter(([k, v]) => v != null && WEIGHTS[k] > 0);
  if (!have.length) return { score: null };
  const w = have.reduce((a, [k]) => a + WEIGHTS[k], 0);
  return { score: Math.round(have.reduce((a, [k, v]) => a + WEIGHTS[k] * v, 0) / w) };
}
