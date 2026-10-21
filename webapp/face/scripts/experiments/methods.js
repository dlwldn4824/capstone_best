// Alternative pulse pipelines at the Sample[] level. Does NOT modify src/.
// analyzeX(samples, opt) mirrors src/pipeline/index.js analyze() but makes each stage pluggable:
//   extract: 'pos' | 'chrom' | 'lgi' | 'omit'      (rPPG projection)
//   fuse:    'best' (current: one ROI/combined with max SNR for the whole scan) | 'window' (per-window SNR-weighted ROI fusion)
//   cancel:  null | 'wls' (sliding-window least squares on motion refs, after projection) | 'nlms' | 'rgb' (wls on each RGB channel before projection)
//   gate:    false | true (drop projection windows that touch large landmark-velocity bursts / talking)
// Quality uses src assessQuality with the SAME gates as production (coverage, interference, roiAgree from this method's per-ROI bpm).
import { pos } from '../../src/pipeline/pos.js';
import { bandpass } from '../../src/pipeline/filter.js';
import { estimateBpm, amplitudeAt } from '../../src/pipeline/spectrum.js';
import { hrvFromPulse } from '../../src/pipeline/hrv.js';
import { assessQuality, ROBUST } from '../../src/pipeline/quality.js';
import { toUniform, coverageOf, GRID_FS } from '../../src/pipeline/resample.js';
import { ROIS, PULSE_FILTER, SEARCH_BAND, SPEC_OPTS, HRV_GATE } from '../../src/pipeline/index.js';

const FS = GRID_FS;
const avg3 = s => [0, 1, 2].map(c => (s.forehead[c] + s.lcheek[c] + s.rcheek[c]) / 3);
const bp = x => bandpass(Float32Array.from(x), FS, PULSE_FILTER[0], PULSE_FILTER[1]);
function stdA(a, i0 = 0, i1 = a.length) { let m = 0; for (let i = i0; i < i1; i++) m += a[i]; m /= (i1 - i0); let s = 0; for (let i = i0; i < i1; i++) s += (a[i] - m) ** 2; return Math.sqrt(s / (i1 - i0)); }

// ---------- projections (windowed overlap-add, 1.6 s). skip[i]=1 -> windows touching i are not used ----------
function windowed(rgb, l, skip, proj) {
  const n = rgb.length, h = new Float32Array(n);
  if (n < l) return h;
  let bad = 0; if (skip) for (let i = 0; i < l; i++) bad += skip[i];
  for (let t = 0; t + l <= n; t++) {
    if (t > 0 && skip) bad += skip[t + l - 1] - skip[t - 1];
    if (bad > 0) continue;
    let mr = 0, mg = 0, mb = 0;
    for (let i = t; i < t + l; i++) { mr += rgb[i][0]; mg += rgb[i][1]; mb += rgb[i][2]; }
    mr /= l; mg /= l; mb /= l;
    if (!mr || !mg || !mb) continue;
    const C = [new Float32Array(l), new Float32Array(l), new Float32Array(l)];
    for (let i = 0; i < l; i++) { C[0][i] = rgb[t + i][0] / mr - 1; C[1][i] = rgb[t + i][1] / mg - 1; C[2][i] = rgb[t + i][2] / mb - 1; }
    const p = proj(C, l);
    let m = 0; for (let i = 0; i < l; i++) m += p[i]; m /= l;
    for (let i = 0; i < l; i++) h[t + i] += p[i] - m;
  }
  return h;
}
const projPOS = (C, l) => {
  const s1 = new Float32Array(l), s2 = new Float32Array(l);
  for (let i = 0; i < l; i++) { s1[i] = C[1][i] - C[2][i]; s2[i] = -2 * C[0][i] + C[1][i] + C[2][i]; }
  const a = stdA(s1) / (stdA(s2) + 1e-9); const p = new Float32Array(l);
  for (let i = 0; i < l; i++) p[i] = s1[i] + a * s2[i];
  return p;
};
// LGI (Pilz 2018): remove the principal direction of the normalized RGB covariance, take the green row
const projLGI = (C, l) => {
  const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < l; i++) for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) S[a][b] += C[a][i] * C[b][i];
  let u = [1, 1, 1];
  for (let it = 0; it < 20; it++) { const v = [0, 1, 2].map(a => S[a][0] * u[0] + S[a][1] * u[1] + S[a][2] * u[2]); const nn = Math.hypot(...v) || 1; u = v.map(x => x / nn); }
  const p = new Float32Array(l);
  for (let i = 0; i < l; i++) { const d = u[0] * C[0][i] + u[1] * C[1][i] + u[2] * C[2][i]; p[i] = C[1][i] - u[1] * d; }
  return p;
};
// OMIT (Casado 2023) approximation on mean-normalized RGB: project out the skin-tone direction [1,1,1]/sqrt3, green row
const projOMIT = (C, l) => { const p = new Float32Array(l); for (let i = 0; i < l; i++) p[i] = C[1][i] - (C[0][i] + C[1][i] + C[2][i]) / 3; return p; };

// CHROM (de Haan & Jeanne 2013): X=3R-2G, Y=1.5R+G-1.5B on normalized RGB, band-pass X,Y, S = Xf - a*Yf per window (Hann OLA)
function chrom(rgb, skip) {
  const n = rgb.length, l = Math.round(1.6 * FS), out = new Float32Array(n);
  if (n < l) return out;
  // centered moving-mean normalization (1.6 s)
  const half = l >> 1, X = new Float32Array(n), Y = new Float32Array(n);
  const cs = [0, 1, 2].map(c => { const a = new Float64Array(n + 1); for (let i = 0; i < n; i++) a[i + 1] = a[i] + rgb[i][c]; return a; });
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - half), b = Math.min(n, i + half + 1);
    const m = cs.map(c => (c[b] - c[a]) / (b - a));
    const r = rgb[i][0] / m[0], g = rgb[i][1] / m[1], bl = rgb[i][2] / m[2];
    X[i] = 3 * r - 2 * g; Y[i] = 1.5 * r + g - 1.5 * bl;
  }
  const Xf = bp(X), Yf = bp(Y);
  const hop = l >> 1;
  for (let t = 0; t + l <= n; t += hop) {
    if (skip) { let bad = 0; for (let i = t; i < t + l; i++) bad += skip[i]; if (bad) continue; }
    const a = stdA(Xf, t, t + l) / (stdA(Yf, t, t + l) + 1e-9);
    let m = 0; for (let i = t; i < t + l; i++) m += Xf[i] - a * Yf[i]; m /= l;
    for (let i = 0; i < l; i++) out[t + i] += (Xf[t + i] - a * Yf[t + i] - m) * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (l - 1)));
  }
  return out;
}

export function extract(rgb, kind, skip) {
  const l = Math.round(1.6 * FS);
  if (kind === 'pos') return skip ? windowed(rgb, l, skip, projPOS) : pos(rgb, FS);
  if (kind === 'chrom') return chrom(rgb, skip);
  if (kind === 'lgi') return windowed(rgb, l, skip, projLGI);
  if (kind === 'omit') return windowed(rgb, l, skip, projOMIT);
  throw new Error(kind);
}

// ---------- motion references (from landmarks only) ----------
export function motionRefs(rows) {
  const x = rows.map(s => s.faceCenter[0] / Math.max(s.faceWidth, 1));
  const y = rows.map(s => s.faceCenter[1] / Math.max(s.faceWidth, 1));
  const w = rows.map(s => Math.log(Math.max(s.faceWidth, 1)));
  const lp = a => bandpass(Float32Array.from(a), FS, 0.05, 6);       // remove DC, keep shape
  const X = lp(x), Y = lp(y), Wd = lp(w);
  const d = a => Float32Array.from(a, (v, i) => (a[Math.min(a.length - 1, i + 1)] - a[Math.max(0, i - 1)]) * FS / 2);
  const sq = a => { const s = stdA(a) || 1; return Float32Array.from(a, v => (v / s) ** 2); };
  return [X, Y, Wd, d(X), d(Y), d(Wd), sq(X), sq(Y)].map(bp);
}

// sliding-window ridge LS: y ≈ R·w per 4 s window (hop 1 s), Hann overlap-add of residual
export function wlsCancel(y, refs, winSec = 4, lambda = 1e-3) {
  const n = y.length, l = Math.min(n, Math.round(winSec * FS)), hop = Math.max(1, Math.round(FS));
  const k = refs.length, out = new Float32Array(n), wsum = new Float32Array(n);
  const scale = refs.map(r => stdA(r) || 1);
  for (let t = 0; ; t += hop) {
    const t0 = Math.min(t, n - l);
    const A = Array.from({ length: k }, () => new Float64Array(k)), b = new Float64Array(k);
    for (let i = t0; i < t0 + l; i++) for (let a = 0; a < k; a++) { const ra = refs[a][i] / scale[a]; b[a] += ra * y[i]; for (let c = a; c < k; c++) A[a][c] += ra * refs[c][i] / scale[c]; }
    for (let a = 0; a < k; a++) { for (let c = 0; c < a; c++) A[a][c] = A[c][a]; A[a][a] += lambda * l; }
    const w = solve(A, b);
    for (let i = 0; i < l; i++) {
      const j = t0 + i, hw = 0.5 - 0.5 * Math.cos(2 * Math.PI * (i + 0.5) / l);
      let e = y[j]; for (let a = 0; a < k; a++) e -= w[a] * refs[a][j] / scale[a];
      out[j] += hw * e; wsum[j] += hw;
    }
    if (t0 === n - l) break;
  }
  for (let i = 0; i < n; i++) out[i] = wsum[i] > 1e-6 ? out[i] / wsum[i] : y[i];
  return out;
}
function solve(A, b) { // Gaussian elimination, small k
  const k = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < k; c++) {
    let p = c; for (let r = c + 1; r < k; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]]; const d = M[c][c] || 1e-12;
    for (let r = c + 1; r < k; r++) { const f = M[r][c] / d; for (let j = c; j <= k; j++) M[r][j] -= f * M[c][j]; }
  }
  const x = new Float64Array(k);
  for (let r = k - 1; r >= 0; r--) { let s = M[r][k]; for (let j = r + 1; j < k; j++) s -= M[r][j] * x[j]; x[r] = s / (M[r][r] || 1e-12); }
  return x;
}
// NLMS (online, causal), run forward then backward and averaged (zero-phase)
export function nlmsCancel(y, refs, mu = 0.02) {
  const run = (yy, rr) => {
    const n = yy.length, k = rr.length, w = new Float64Array(k), out = new Float32Array(n);
    const sc = rr.map(r => stdA(r) || 1);
    for (let i = 0; i < n; i++) {
      let yh = 0, pw = 1e-9; for (let a = 0; a < k; a++) { const v = rr[a][i] / sc[a]; yh += w[a] * v; pw += v * v; }
      const e = yy[i] - yh; out[i] = e;
      for (let a = 0; a < k; a++) w[a] += mu * e * rr[a][i] / sc[a] / pw;
    }
    return out;
  };
  const f = run(y, refs), rv = a => Float32Array.from(a).reverse();
  const bk = rv(run(rv(y), refs.map(rv)));
  return Float32Array.from(f, (v, i) => (v + bk[i]) / 2);
}

// ---------- burst gating ----------
// velocity proxy: displacement over ±5 frames (0.33 s) / face width + |log scale change|; mask > max(abs, k*median), dilated
export const GATE = { absFrac: 0.03, relMed: 5, dilateSec: 0.4, mouth: 0.35, maxFrac: 0.4 };
export function burstMask(rows, g = GATE) {
  const n = rows.length, v = new Float32Array(n), m = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const a = rows[Math.max(0, i - 5)], b = rows[Math.min(n - 1, i + 5)];
    v[i] = Math.hypot(b.faceCenter[0] - a.faceCenter[0], b.faceCenter[1] - a.faceCenter[1]) / Math.max(rows[i].faceWidth, 1) + Math.abs(Math.log(b.faceWidth / a.faceWidth));
  }
  const med = [...v].sort((x, y) => x - y)[n >> 1] || 0, thr = Math.max(g.absFrac, g.relMed * med);
  const d = Math.round(g.dilateSec * FS);
  for (let i = 0; i < n; i++) if (v[i] > thr || (g.mouth != null && (rows[i].mouthOpen || 0) > g.mouth)) for (let j = Math.max(0, i - d); j <= Math.min(n - 1, i + d); j++) m[j] = 1;
  return m;
}

// ---------- per-window ROI fusion ----------
function fuseWindows(pulses, winSec = 6) {
  const n = pulses[0].length, l = Math.min(n, Math.round(winSec * FS)), hop = Math.round(FS);
  const out = new Float32Array(n), ws = new Float32Array(n);
  for (let t = 0; ; t += hop) {
    const t0 = Math.min(t, n - l);
    const seg = pulses.map(p => p.subarray(t0, t0 + l));
    const sn = seg.map(s => { const sd = stdA(s); if (!(sd > 0)) return { w: 0, sd: 1 }; const e = estimateBpm(s, FS, SEARCH_BAND, 1024, SPEC_OPTS); return { w: Number.isFinite(e.snrDb) ? 10 ** (e.snrDb / 10) : 0, sd }; });
    for (let i = 0; i < l; i++) {
      const hw = 0.5 - 0.5 * Math.cos(2 * Math.PI * (i + 0.5) / l);
      let v = 0; for (let r = 0; r < seg.length; r++) v += sn[r].w * seg[r][i] / sn[r].sd;
      out[t0 + i] += hw * v; ws[t0 + i] += hw;
    }
    if (t0 === n - l) break;
  }
  for (let i = 0; i < n; i++) if (ws[i] > 0) out[i] /= ws[i];
  return out;
}

function relSeries(x) { let m = 0; for (const v of x) m += v; m /= x.length || 1; return Float32Array.from(x, v => (m ? v / m - 1 : 0)); }
function interferenceAt(rows, rgb, fHz) {
  const mx = amplitudeAt(bp(rows.map(s => s.faceCenter[0] / Math.max(s.faceWidth, 1))), FS, fHz);
  const my = amplitudeAt(bp(rows.map(s => s.faceCenter[1] / Math.max(s.faceWidth, 1))), FS, fHz);
  const m = mx.amp >= my.amp ? mx : my;
  const light = amplitudeAt(bp(relSeries(rows.map(s => s.brightness))), FS, fHz);
  const green = amplitudeAt(bp(relSeries(rgb.map(c => c[1]))), FS, fHz);
  return { motionAmp: m.amp, motionFrac: m.frac, lightAmp: light.amp, lightRatio: green.amp > 0 ? light.amp / green.amp : Infinity };
}

// regress each normalized RGB channel on motion refs before projection
function rgbCancel(rgb, refs) {
  const ch = [0, 1, 2].map(c => { const raw = rgb.map(v => v[c]); let m = 0; for (const v of raw) m += v; m /= raw.length; return Float32Array.from(raw, v => v / m - 1); });
  // only cancel the pulse-band part; keep slow part
  const out = ch.map(x => { const hi = bp(x); const lo = Float32Array.from(x, (v, i) => v - hi[i]); const c = wlsCancel(hi, refs); return Float32Array.from(lo, (v, i) => 1 + v + c[i]); });
  return rgb.map((_, i) => [out[0][i], out[1][i], out[2][i]]);
}

export function analyzeX(samples, opt = {}) {
  const { extract: kind = 'pos', fuse = 'best', cancel = null, gate = false, gateOpt = GATE, hrv = true, resp = false } = opt;
  const coverage = coverageOf(samples);
  const { rows, valid } = toUniform(samples, FS);
  const n = rows.length;
  if (n < 60) return { bpm: NaN, snrDb: -Infinity, quality: { pass: false, reason: 'short' }, hrvReliable: false };
  const mask = gate ? burstMask(rows, gateOpt) : null;
  let gatedFrac = 0; if (mask) { for (const v of mask) gatedFrac += v; gatedFrac /= n; }
  const useMask = mask && gatedFrac <= gateOpt.maxFrac ? mask : null;
  const refs = cancel ? motionRefs(rows) : null;
  const cands = { all: rows.map(avg3) };
  for (const r of ROIS) cands[r] = rows.map(s => s[r]);
  const per = {};
  for (const [name, rgb0] of Object.entries(cands)) {
    const rgb = cancel === 'rgb' ? rgbCancel(rgb0, refs) : rgb0;
    let p = bp(extract(rgb, kind, useMask));
    if (cancel === 'wls') p = wlsCancel(p, refs);
    else if (cancel === 'nlms') p = nlmsCancel(p, refs);
    if (useMask) for (let i = 0; i < n; i++) if (useMask[i]) p[i] = 0;
    const sp = estimateBpm(p, FS, SEARCH_BAND, 4096, SPEC_OPTS);
    per[name] = { bpm: sp.bpm, snrDb: sp.snrDb, pulse: p };
  }
  let chosenName, chosen;
  if (fuse === 'window') {
    const p = fuseWindows(['all', ...ROIS].map(k => per[k].pulse));
    const sp = estimateBpm(p, FS, SEARCH_BAND, 4096, SPEC_OPTS);
    chosenName = 'fused'; chosen = { bpm: sp.bpm, snrDb: sp.snrDb, pulse: p };
  } else {
    chosenName = Object.keys(per).reduce((a, b) => (per[b].snrDb > per[a].snrDb ? b : a), 'all'); chosen = per[chosenName];
  }
  const roiAgree = ROIS.filter(r => Math.abs(per[r].bpm - chosen.bpm) <= ROBUST.roiAgreeBpm).length;
  const interference = interferenceAt(rows, chosenName === 'fused' ? cands.all : cands[chosenName], chosen.bpm / 60);
  const quality = assessQuality(samples, chosen.snrDb, undefined, { coverage, interference, roiAgree });
  if (mask && gatedFrac > gateOpt.maxFrac) { quality.pass = false; quality.reason = 'gated'; }
  let hv = { pairs: 0, rmssd: NaN };
  if (hrv) {
    const vv = useMask ? Uint8Array.from(valid, (v, i) => v && !useMask[i]) : valid;
    hv = hrvFromPulse(chosen.pulse, FS, chosen.bpm, 250, vv);
  }
  const hrvReliable = Number.isFinite(chosen.snrDb) && chosen.snrDb >= HRV_GATE.snrDbMin && hv.pairs >= HRV_GATE.pairsMin && quality.pass;
  return { bpm: chosen.bpm, snrDb: chosen.snrDb, quality, roiAgree, roiBest: chosenName, perRoi: per, gatedFrac, rmssd: hv.rmssd, hrvPairs: hv.pairs, hrvReliable, pulse: chosen.pulse };
}
