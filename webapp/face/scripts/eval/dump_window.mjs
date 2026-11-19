// 창 하나를 face 파이프라인(analyze)으로 돌리고 맥파·스펙트럼까지 그대로 뱉는다.
//
//   node scripts/eval/dump_window.mjs window.json > dump.json
//
// 입력  = { key, t: [초...], roi: [[[r,g,b] x3] x 프레임] }   (mcd_windows.mjs 와 같은 모양)
// 출력  = { key, bpm, snrDb, fs, pulse: [...], spec: { f: [...], p: [...] }, quality, ... }
//
// 포스터 그림 1(얼굴 맥파 vs 손끝 센서)을 '앱이 실제로 돌리는 코드'로 그리려고 만들었다.
// docs/presentation/poster/make_fig_match.py 가 부른다.
import { readFileSync } from 'node:fs';
import { analyze, WINDOW } from '../../src/pipeline/index.js';

const FACE_W = 200, FACE_C = [320, 240];

const w = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const samples = w.t.map((t, i) => {
  const [fh, lc, rc] = w.roi[i];
  const brightness = (fh[0]+fh[1]+fh[2] + lc[0]+lc[1]+lc[2] + rc[0]+rc[1]+rc[2]) / 9;
  return { t: t * 1000, forehead: fh, lcheek: lc, rcheek: rc,
    faceWidth: FACE_W, faceCenter: FACE_C, brightness, blink: 0, mouthOpen: 0 };
});

// RETRY=off 면 구간 선택을 끈다 — '전체로 보면 어땠나'를 따로 보려고
const r = analyze(samples, { resp: false, windowRetry: process.env.RETRY !== 'off' });

// 구간별로도 따로 돌려 둔다 — 어느 구간을 버리고 어느 구간을 살렸는지 그림으로 보이려고.
// bestWindow 와 같은 규칙(WINDOW.sec 길이, stepSec 간격)으로 자른다.
const span = (samples[samples.length - 1].t - samples[0].t) / 1000;
const wins = [];
if (process.env.WINDOWS !== 'off') {
  const t0 = samples[0].t;
  const starts = [];
  for (let s = 0; s + WINDOW.sec <= span + 1e-6; s += WINDOW.stepSec) starts.push(s);
  if (span > WINDOW.sec && starts[starts.length - 1] < span - WINDOW.sec - 1e-6) starts.push(span - WINDOW.sec);
  for (const s of starts) {
    const part = samples.filter(x => x.t >= t0 + s * 1000 && x.t < t0 + (s + WINDOW.sec) * 1000);
    if (part.length < 60) continue;
    try {
      const w = analyze(part, { resp: false, windowRetry: false });
      wins.push({ start: +s.toFixed(2), end: +(s + WINDOW.sec).toFixed(2),
        bpm: w.bpm, snr: w.snrDb, pass: !!w.quality.pass, reason: w.quality.reason });
    } catch { /* 이 구간은 건너뛴다 */ }
  }
}

process.stdout.write(JSON.stringify({
  key: w.key,
  bpm: r.bpm, snrDb: r.snrDb, fs: r.fsGrid, method: r.method,
  pass: !!r.quality.pass, reason: r.quality.reason, window: r.window,
  perRoi: r.perRoi, span: +span.toFixed(3), windows: wins,
  pulse: Array.from(r.debug.pulse, v => +v.toFixed(6)),
  spec: { f: Array.from(r.debug.spectrum.f, v => +v.toFixed(5)),
          p: Array.from(r.debug.spectrum.p, v => +v.toExponential(5)) },
}));
