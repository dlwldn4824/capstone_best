// Motion scenarios layered on top of scripts/robustness/gen.js (which is not modified).
// gen() gives physiology + camera (PPG with dicrotic notch, RR jitter/RSA, AE, WB, flicker, drops, gaps).
// Here we add realistic, non-periodic motion and couple it into every Sample field:
//   faceCenter (nose tip, px) / faceWidth (px) / per-ROI RGB (shading, specular, ROI slip) / mouthOpen / blink events.
//
// Motion state m(t) in face-width units: dx, dy (translation), ds (relative scale), yaw, pitch (rad), jaw (0..1).
// Per-ROI RGB:  rgb_c' = rgb_c * (1 + sh_r(t) * (1 + chroma * ch_c) + slip_r(t)) + spec_r(t) * 255
//   sh_r   = shading from face pose relative to a light gradient (random per seed, per ROI; includes yaw^2, pitch^2)
//   slip_r = ROI-polygon lag/jitter mixing in non-skin pixels: proportional to landmark velocity (1-2 frame lag)
//   spec_r = specular highlight, nonlinear max(0, .)^2 of pose, added equally to R,G,B in absolute units
// Handheld tremor moves the CAMERA, so it shifts the image (dx, dy) but barely changes face shading (camGain ~0.15).
import { gen, rng, gauss, makeBeats, rrInWindow, rmssdOf } from '../robustness/gen.js';
import { REAL, bpmFor, SEEDS } from '../robustness/evalrun.js';
export { SEEDS, bpmFor, REAL };

const BASE = [150, 110, 95];
const ROI = ['forehead', 'lcheek', 'rcheek'];

// sum of sinusoids with random freqs in [f0,f1] -> band-limited noise with unit RMS
function bandNoise(r, f0, f1, k = 8) {
  const comps = Array.from({ length: k }, () => ({ f: f0 + r() * (f1 - f0), ph: r() * 6.283, a: 0.5 + r() }));
  const rms = Math.sqrt(comps.reduce((s, c) => s + c.a * c.a / 2, 0));
  return t => comps.reduce((s, c) => s + c.a * Math.sin(6.283 * c.f * t + c.ph), 0) / rms;
}
const rc = x => (x <= 0 || x >= 1 ? 0 : 0.5 - 0.5 * Math.cos(2 * Math.PI * x)); // raised-cosine bump on [0,1]

// Scenario definitions. Each returns { pose(t) -> {dx,dy,ds,yaw,pitch,jaw}, cam(t) -> {dx,dy} (camera-only shift), lightDrift }
export const SCENARIOS = {
  still: () => ({}),
  // handheld: phone tremor 2–8 Hz, image shift RMS 0.4–0.8% face width, tiny scale. Camera motion -> little shading.
  tremor: r => {
    const nx = bandNoise(r, 2, 8), ny = bandNoise(r, 2, 8), ns = bandNoise(r, 2, 8);
    const a = 0.004 + 0.004 * r();
    return { cam: t => ({ dx: a * nx(t), dy: a * ny(t), ds: 0.3 * a * ns(t) }) };
  },
  // slow postural sway 0.2–0.5 Hz, 2–4% lateral, 1% vertical, 1–2% scale (forward/back) -> full shading
  sway: r => {
    const f = 0.2 + 0.3 * r(), nx = bandNoise(r, f * 0.8, f * 1.2, 4), ny = bandNoise(r, f * 0.8, f * 1.2, 4), ns = bandNoise(r, 0.1, 0.4, 4);
    const ax = 0.02 + 0.02 * r(), as = 0.01 + 0.01 * r();
    return { pose: t => ({ dx: ax * nx(t), dy: 0.01 * ny(t), ds: as * ns(t), yaw: 0.05 * nx(t), pitch: 0.02 * ny(t) }) };
  },
  // continuous nodding 0.8–2.0 Hz (HR band!), pitch 3–6 deg, amplitude-modulated. nodHR: nod at exactly the mean heart rate (worst case)
  nodHR: (r, cfg) => { const s = SCENARIOS.nod(r, cfg, (cfg.bpm ?? 72) / 60); return s; },
  nod: (r, cfg, fix) => {
    const f0 = 0.8 + 1.2 * r(), f = fix ?? f0, am = bandNoise(r, 0.05, 0.2, 3), ph = r() * 6.283, deg = 3 + 3 * r();
    return { pose: t => { const s = Math.sin(6.283 * f * t + ph) * (1 + 0.3 * am(t)); return { dy: 0.012 * s, pitch: deg / 57.3 * s, ds: 0.003 * s }; } };
  },
  // talking: 3–5 bursts of 1.5–4 s, jaw at 3–6 Hz syllable rate; cheeks deform, small head motion
  talk: r => {
    const nb = 3 + Math.floor(r() * 3), bursts = [];
    for (let k = 0; k < nb; k++) { const d = 1.5 + 2.5 * r(); const s = 1 + r() * (28 - d); bursts.push([s, s + d]); }
    const fj = 3 + 3 * r(), nj = bandNoise(r, fj * 0.7, fj * 1.3, 5), nh = bandNoise(r, 1, 4, 5);
    return { pose: t => {
      let on = 0; for (const [a, b] of bursts) if (t >= a && t < b) on = Math.max(on, Math.min(1, (t - a) / 0.2, (b - t) / 0.2));
      const jaw = on * Math.max(0, 0.45 + 0.4 * nj(t));
      return { jaw, dy: on * 0.006 * nh(t), pitch: on * 0.03 * nh(t), dx: on * 0.003 * nj(t) };
    } };
  },
  // one big head turn: yaw to ±25–35 deg and back over 1.5–2.5 s at a random time
  turn: r => {
    const t0 = 5 + 18 * r(), d = 1.5 + r(), yaw = (r() < 0.5 ? -1 : 1) * (25 + 10 * r()) / 57.3;
    return { pose: t => { const b = rc((t - t0) / d); return { yaw: yaw * b, dx: 0.08 * Math.sign(yaw) * b, pitch: 0.05 * b }; } };
  },
  // walking with the phone: head bob at step freq 1.6–2.0 Hz (vertical), lateral at f/2, + hand tremor + light changes
  walk: r => {
    const f = 1.6 + 0.4 * r(), ph = r() * 6.283, nx = bandNoise(r, 2, 8), ny = bandNoise(r, 2, 8), ab = 0.02 + 0.01 * r();
    return {
      pose: t => ({ dy: ab * Math.sin(6.283 * f * t + ph), dx: 0.02 * Math.sin(3.1415 * f * t + ph), ds: 0.01 * Math.sin(6.283 * f * t + ph + 1),
        pitch: 0.04 * Math.sin(6.283 * f * t + ph), yaw: 0.05 * Math.sin(3.1415 * f * t + ph) }),
      cam: t => ({ dx: 0.006 * nx(t), dy: 0.006 * ny(t), ds: 0 }),
      genExtra: { drift: 0.08 },
    };
  },
  // realistic handheld session: tremor + sway + one short talk burst + small turn
  combo: r => {
    const a = SCENARIOS.tremor(r), b = SCENARIOS.sway(r), c = SCENARIOS.talk(r), t0 = 8 + 14 * r(), y = (r() < 0.5 ? -1 : 1) * 0.25;
    return { cam: a.cam, pose: t => { const p = b.pose(t), q = c.pose(t), k = rc((t - t0) / 1.5) * 0.5;
      return { dx: p.dx + q.dx + 0.04 * Math.sign(y) * rc((t - t0) / 1.5), dy: p.dy + q.dy, ds: p.ds, yaw: p.yaw + y * rc((t - t0) / 1.5), pitch: p.pitch + q.pitch, jaw: k * 0 + q.jaw }; } };
  },
};

// Build one scan. cfg: gen() options + { scenario, motionScale, blinkPerMin }
export function scan(cfg) {
  // obs: 'ideal' | 'hard'. hard = landmark noise 1.5 px, shading driven by pose 2 frames earlier than the landmark (rolling shutter /
  // tracker smoothing), tanh saturation, and an unobserved multiplicative modulation (expression / light changes) — limits what
  // landmark-based regression can explain.
  // bcgPx: ballistocardiographic head motion (px, vertical, pulse-synchronous) in the landmarks — a real effect that could let
  // motion regression remove pulse.
  const { scenario = 'still', motionScale = 1, blinkPerMin = null, seed = 1, obs = 'ideal', bcgPx = 0 } = cfg;
  const hard = obs === 'hard';
  const r = rng(seed * 7 + 31337);
  const sc = SCENARIOS[scenario](r, cfg);
  const respHz = cfg.respHz ?? 0.18 + 0.15 * rng(seed + 555)();
  const g = { ...REAL, ...sc.genExtra, respHz, blinkRate: 0, ...cfg };
  delete g.scenario; delete g.motionScale; delete g.blinkPerMin; delete g.obs; delete g.bcgPx;
  const { samples, truth } = gen(g);
  const beats = makeBeats({ bpm: g.bpm ?? 72, dur: g.dur ?? 30, rrJitterMs: g.rrJitterMs || 0, rsaMs: g.rsaMs || 0, respHz, afFrac: g.afFrac || 0, r: rng(seed) });

  // per-seed coupling coefficients
  const light = { gx: (r() - 0.5) * 1.2, gy: -0.3 - 0.4 * r(), gs: 0.2 + 0.3 * r() };   // light gradient (per face-width unit)
  const roiK = {
    forehead: { yaw: 0.04 * (r() - 0.5), pitch: 0.25 + 0.15 * r(), jaw: 0.003, ox: 0, oy: -0.25, slip: 0.15 * (r() - 0.3), spec: 0.03 + 0.03 * r() },
    lcheek: { yaw: 0.25 + 0.15 * r(), pitch: 0.08, jaw: 0.02 + 0.02 * r(), ox: -0.2, oy: 0.1, slip: 0.25 * (r() - 0.3), spec: 0.01 },
    rcheek: { yaw: -(0.25 + 0.15 * r()), pitch: 0.08, jaw: 0.02 + 0.02 * r(), ox: 0.2, oy: 0.1, slip: 0.25 * (r() - 0.3), spec: 0.01 },
  };
  const chroma = 0.15 + 0.2 * r(), camGain = 0.15, W0 = g.faceWidth || 200;
  const zero = { dx: 0, dy: 0, ds: 0, yaw: 0, pitch: 0, jaw: 0 };
  const P = t => ({ ...zero, ...(sc.pose ? sc.pose(t) : {}) });
  const C = t => ({ dx: 0, dy: 0, ds: 0, ...(sc.cam ? sc.cam(t) : {}) });
  const ms = motionScale;
  // blink events (Poisson), duration 0.15–0.3 s; truth = rate parameter
  const bRate = blinkPerMin ?? 8 + 22 * rng(seed + 777)();
  const br = rng(seed + 888), blinks = [];
  for (let t = 0; ; ) { t += -Math.log(1 - br()) * 60 / bRate; if (t > (g.dur ?? 30)) break; blinks.push([t, t + 0.15 + 0.15 * br()]); }
  const nr = rng(seed + 999);
  const lag = 0.05; // ROI polygon lag (s)
  const lmNoise = hard ? 1.5 : 0.4, shLag = hard ? 0.067 : 0, latent = bandNoise(rng(seed + 4242), 0.3, 3, 6);

  for (const s of samples) {
    const t = s.t / 1000;
    const p = P(t), c = C(t), pl = P(t - lag), cl = C(t - lag);
    for (const k of Object.keys(p)) p[k] *= ms; for (const k of Object.keys(c)) c[k] *= ms;
    for (const k of Object.keys(pl)) pl[k] *= ms; for (const k of Object.keys(cl)) cl[k] *= ms;
    const imgDx = p.dx + c.dx + 0.3 * Math.sin(p.yaw), imgDy = p.dy + c.dy + 0.3 * Math.sin(p.pitch);
    const imgDxL = pl.dx + cl.dx + 0.3 * Math.sin(pl.yaw), imgDyL = pl.dy + cl.dy + 0.3 * Math.sin(pl.pitch);
    const vel = Math.hypot(imgDx - imgDxL, imgDy - imgDyL); // face-width per lag
    const ps = shLag ? P(t - shLag) : p, cs2 = shLag ? C(t - shLag) : c;
    if (shLag) { for (const k of Object.keys(ps)) ps[k] *= ms; for (const k of Object.keys(cs2)) cs2[k] *= ms; }
    for (const name of ROI) {
      const k = roiK[name];
      let pose = light.gx * (ps.dx + camGain * cs2.dx) + light.gy * (ps.dy + camGain * cs2.dy) + light.gs * (ps.ds + camGain * cs2.ds)
        + k.yaw * ps.yaw + k.pitch * ps.pitch + 0.3 * ps.yaw * ps.yaw + 0.3 * ps.pitch * ps.pitch + k.jaw * ps.jaw;
      if (hard) pose = Math.tanh(pose * 4) / 4 * (1 + 0.4 * latent(t));
      const slip = k.slip * vel * 3 + 0.01 * Math.abs(p.jaw) * (name === 'forehead' ? 0 : 1) * gauss(nr) * 0.2;
      const spec = k.spec * Math.max(0, pose) ** 2 * 10;
      s[name] = s[name].map((v, ch) => v * (1 + pose * (1 + chroma * [0, -1, 1][ch]) + slip) + spec * 255);
    }
    const W = W0 * (1 + p.ds + c.ds) * (1 - 0.25 * (1 - Math.cos(p.yaw)));
    s.faceWidth = W + gauss(nr) * lmNoise;
    s.faceCenter = [s.faceCenter[0] + imgDx * W0 + gauss(nr) * lmNoise, s.faceCenter[1] + imgDy * W0 + gauss(nr) * lmNoise];
    if (bcgPx) { let j = 0; while (j < beats.length - 2 && beats[j + 1] <= t) j++; s.faceCenter[1] += bcgPx * Math.sin(2 * Math.PI * (t - beats[j]) / (beats[j + 1] - beats[j])); }
    s.mouthOpen = Math.min(1, Math.max(0, p.jaw));
    s.blink = blinks.some(([a, b]) => t >= a && t < b) ? 0.9 : 0.02;
    const lum = ROI.reduce((a, n) => a + (s[n][0] + s[n][1] + s[n][2]) / 3, 0) / 3;
    s.brightness = lum * (g.brightness ?? 140) / ((BASE[0] + BASE[1] + BASE[2]) / 3);
  }
  return { samples, truth: { ...truth, respPerMin: respHz * 60, blinkPerMin: bRate }, beats, blinks };
}

// truth over a sub-window [t0, t1] s
export function truthIn(beats, t0, t1) {
  const rr = rrInWindow(beats, t0, t1);
  return { bpm: 60000 / (rr.reduce((a, b) => a + b, 0) / rr.length), rr, rmssd: rmssdOf(rr) };
}
export const cut = (samples, t0, t1) => samples.filter(s => s.t >= t0 * 1000 && s.t <= t1 * 1000);
