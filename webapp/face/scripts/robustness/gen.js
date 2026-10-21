// Adversarial synthetic generator for robustness audit. Does NOT touch src/.
// Continuous-time physiology + camera model, sampled at (possibly irregular) capture times.
//
// rgb_c(t) = base_c * L(t) * wb_c(t) * (1 + amp*g_c*pulse(t) + resp(t) + shade(t)) + spec(t) + noise
// reported Sample.t = capture time + timestamp jitter (what performance.now() would give)

export function rng(seed) {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    let t = (s += 0x6D2B79F5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
export function gauss(r) { let u = 0, v = 0; while (u === 0) u = r(); while (v === 0) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }

// PPG shape: systolic Gaussian + dicrotic wave. Normalized to zero mean, unit std over one cycle.
function makeShape({ dicrotic = 0.3, h2 = 0, sinus = false, sw = 0.1 }) {
  const N = 2000, raw = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    const p = i / N;
    if (sinus) raw[i] = Math.sin(2 * Math.PI * p) + h2 * Math.sin(4 * Math.PI * p);
    else {
      const g = (c, w) => Math.exp(-0.5 * ((p - c) / w) ** 2) + Math.exp(-0.5 * ((p - 1 - c) / w) ** 2);
      raw[i] = g(0.22, sw) + dicrotic * g(0.52, 0.1) + h2 * Math.sin(4 * Math.PI * p);
    }
  }
  let m = 0; for (const v of raw) m += v; m /= N;
  let s = 0; for (const v of raw) s += (v - m) ** 2; s = Math.sqrt(s / N);
  for (let i = 0; i < N; i++) raw[i] = (raw[i] - m) / s;
  return p => raw[Math.min(N - 1, Math.floor((p - Math.floor(p)) * N))];
}

// Beat times (s). iid RR jitter + optional RSA (resp-coupled sinus modulation) + optional AF-like irregularity.
export function makeBeats({ bpm, dur, rrJitterMs = 0, rsaMs = 0, respHz = 0.25, afFrac = 0, r }) {
  const beats = [-2 * 60 / bpm];
  let t = beats[0];
  while (t < dur + 3) {
    let rr = 60 / bpm + (rrJitterMs ? gauss(r) * rrJitterMs / 1000 : 0) + rsaMs / 1000 * Math.sin(2 * Math.PI * respHz * t);
    if (afFrac && r() < afFrac) rr *= 0.6 + 0.8 * r();
    rr = Math.max(0.3, rr);
    t += rr; beats.push(t);
  }
  return beats;
}
export function rrInWindow(beats, t0, t1) {
  const rr = [];
  for (let i = 1; i < beats.length; i++) if (beats[i - 1] >= t0 && beats[i] <= t1) rr.push((beats[i] - beats[i - 1]) * 1000);
  return rr;
}
export function rmssdOf(rr) { let s = 0; for (let i = 1; i < rr.length; i++) s += (rr[i] - rr[i - 1]) ** 2; return Math.sqrt(s / (rr.length - 1)); }

const BASE = [150, 110, 95];
const PULSE_G = [0.33, 0.77, 0.53]; // relative channel pulse strength (green strongest), * 0.0042 * amp -> green std ~0.32%

export function gen(o = {}) {
  const {
    seed = 1, bpm = 72, dur = 30, fps = 30,
    amp = 1, noise = 0.6, shape = {},
    rrJitterMs = 0, rsaMs = 0, afFrac = 0,
    respHz = 0.25, respAmp = 0.01, respHeadPx = 0,   // brightness resp mod + head bob in px at resp freq
    drift = 0.03,                                 // slow random-walk illumination (common)
    expoSteps = 0, expoStepMag = 0.1,             // number of auto-exposure steps and their relative magnitude
    wbDrift = 0,                                  // channel-specific gain drift over the window (e.g. 0.05 = 5%)
    flickerHz = 0, flickerAmp = 0,                // mains flicker sampled at capture times (aliases)
    screenHz = 0, screenAmp = 0,                  // screen-light flicker, per-channel unequal
    motionHz = 0, motionShade = 0, motionSpec = 0, motionPx = 0, // periodic head motion
    slowDriftPx = 0,                              // slow linear drift over the window in px (passes per-frame check)
    tsJitterMs = 0, dropFrac = 0, gaps = 0, gapMin = 0.5, gapMax = 2.0,
    dupFrac = 0,                                  // rAF faster than camera: same frame pushed twice with new timestamp
    blinkRate = 0.05, brightness = 140, faceWidth = 200,
    noPulse = false, beatSeed = null,
    motionChroma = 0, flickerChroma = 0,          // channel mismatch of motion shading / flicker (0 = pure common-mode, POS-friendly)
  } = o;
  const r = rng(seed);
  const shp = makeShape(shape);
  const beats = makeBeats({ bpm, dur, rrJitterMs, rsaMs, respHz, afFrac, r: beatSeed == null ? r : rng(beatSeed + 99991) });
  // random-walk drift, smoothed
  const dN = Math.ceil(dur * 10) + 2; const dw = new Float64Array(dN); let acc = 0;
  for (let i = 0; i < dN; i++) { acc = 0.98 * acc + gauss(r) * drift * 0.15; dw[i] = acc; }
  const driftAt = t => { const x = t * 10, i = Math.max(0, Math.min(dN - 2, Math.floor(x))), f = x - i; return dw[i] * (1 - f) + dw[i + 1] * f; };
  const steps = []; for (let k = 0; k < expoSteps; k++) steps.push({ t: 2 + r() * (dur - 4), m: (r() < 0.5 ? -1 : 1) * expoStepMag * (0.5 + 0.5 * r()) });
  const wbDir = [gauss(r), gauss(r), gauss(r)];
  const mPh = r() * 6.28, fPh = r() * 6.28, sPh = r() * 6.28;
  // gaps
  const gapIv = []; for (let k = 0; k < gaps; k++) { const g = gapMin + r() * (gapMax - gapMin); const s = 1 + r() * (dur - 2 - g); gapIv.push([s, s + g]); }

  let bi = 0;
  const pulseAt = t => {
    while (bi < beats.length - 2 && beats[bi + 1] <= t) bi++;
    while (bi > 0 && beats[bi] > t) bi--;
    return shp((t - beats[bi]) / (beats[bi + 1] - beats[bi]));
  };
  const samples = [];
  const nFrames = Math.round(dur * fps);
  for (let i = 0; i < nFrames; i++) {
    const tc = i / fps;                         // capture time
    if (dropFrac && r() < dropFrac) continue;
    if (gapIv.some(([a, b]) => tc >= a && tc < b)) continue;
    const p = noPulse ? 0 : pulseAt(tc);
    let L = 1 + driftAt(tc);
    for (const s of steps) if (tc >= s.t) L *= 1 + s.m;
    const fl = flickerAmp ? flickerAmp * Math.sin(2 * Math.PI * flickerHz * tc + fPh) : 0;
    const resp = respAmp * Math.sin(2 * Math.PI * respHz * tc);
    const mv = Math.sin(2 * Math.PI * motionHz * tc + mPh);
    const shade = motionShade * mv;
    const spec = motionSpec * Math.max(0, mv);
    const scr = screenAmp * Math.sin(2 * Math.PI * screenHz * tc + sPh);
    const rgb = k => BASE.map((b, c) => {
      const wb = 1 + wbDrift * wbDir[c] * (tc / dur - 0.5);
      const scrC = scr * [1.0, 0.6, 1.4][c];      // screen light is bluish/unequal
      const ch = [0, -1, 1][c];
      return b * L * wb * (1 + fl * (1 + flickerChroma * ch)) * (1 + amp * 0.0042 * PULSE_G[c] * k * p + resp + shade * (1 + motionChroma * ch) + scrC) + spec * 255 + gauss(r) * noise;
    });
    const cx = 320 + motionPx * mv + slowDriftPx * (tc / dur) + gauss(r) * 0.5;
    const cy = 240 + motionPx * 0.5 * mv + respHeadPx * Math.sin(2 * Math.PI * respHz * tc) + gauss(r) * 0.5;
    const tRep = tc * 1000 + (tsJitterMs ? (r() * 2 - 1) * tsJitterMs : 0);
    const fh = rgb(1.0), lc = rgb(1.1), rc = rgb(1.05);
    // brightness like src/capture/roi.js: mean (r+g+b)/3 over ROI pixels -> contains pulse + lighting
    const lum = [fh, lc, rc].reduce((a, v) => a + (v[0] + v[1] + v[2]) / 3, 0) / 3;
    const s = {
      t: Math.round(tRep),
      forehead: fh, lcheek: lc, rcheek: rc,
      faceWidth, faceCenter: [cx, cy],
      brightness: lum * brightness / ((BASE[0] + BASE[1] + BASE[2]) / 3),
      blink: r() < blinkRate ? 1 : 0, mouthOpen: 0,
    };
    samples.push(s);
    if (dupFrac && r() < dupFrac) samples.push({ ...s, t: s.t + Math.round(1000 / fps / 2) });
  }
  samples.sort((a, b) => a.t - b.t);
  const rrTrue = rrInWindow(beats, 0, dur);
  return { samples, truth: { bpm: 60000 / (rrTrue.reduce((a, b) => a + b, 0) / rrTrue.length), rr: rrTrue, rmssd: rmssdOf(rrTrue) } };
}

// Proposed fix used for comparison: linear resample to uniform grid by real timestamps.
export function resampleUniform(samples, fs = 30) {
  const t0 = samples[0].t, t1 = samples[samples.length - 1].t;
  const n = Math.floor((t1 - t0) / 1000 * fs) + 1;
  const out = []; let j = 0;
  const lerp = (a, b, f) => Array.isArray(a) ? a.map((v, k) => v + (b[k] - v) * f) : a + (b - a) * f;
  for (let i = 0; i < n; i++) {
    const t = t0 + i * 1000 / fs;
    while (j < samples.length - 2 && samples[j + 1].t < t) j++;
    const a = samples[j], b = samples[j + 1] || a, f = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0;
    const s = { t };
    for (const k of Object.keys(a)) if (k !== 't') s[k] = lerp(a[k], b[k], f);
    out.push(s);
  }
  return out;
}

// stats helpers
export const q = (a, p) => { const s = [...a].filter(Number.isFinite).sort((x, y) => x - y); if (!s.length) return NaN; const i = (s.length - 1) * p, lo = Math.floor(i); return s[lo] + (s[Math.min(s.length - 1, lo + 1)] - s[lo]) * (i - lo); };
export const mean = a => { const f = a.filter(Number.isFinite); return f.reduce((x, y) => x + y, 0) / f.length; };
export const frac = (a, pred) => a.filter(pred).length / a.length;
export const f1 = v => (Number.isFinite(v) ? v.toFixed(1) : String(v));
export const pct = v => (100 * v).toFixed(0) + '%';
export function table(title, header, rows) {
  console.log(`\n### ${title}`);
  console.log('| ' + header.join(' | ') + ' |');
  console.log('|' + header.map(() => '---').join('|') + '|');
  for (const r of rows) console.log('| ' + r.join(' | ') + ' |');
}
