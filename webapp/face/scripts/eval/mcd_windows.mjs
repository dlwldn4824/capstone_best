// MCD-rPPG 창을 face 파이프라인(analyze)으로 돌린다.
//
//   node scripts/eval/mcd_windows.mjs windows.jsonl > results.jsonl
//
// 입력 한 줄 = 창 하나: { key, t: [초...], roi: [[[r,g,b] x3] x 프레임] }  (영역 순서: 이마 · 왼볼 · 오른볼)
// 출력 한 줄 = 그 창의 결과. research/scripts/28_rppg_v3_face.py 가 읽는다.
//
// 이 데이터에는 얼굴 랜드마크가 없다 (23_mcd_extract.py 가 고정 상자로 영역을 뽑는다).
// 그래서 얼굴 폭 · 중심은 상수로 두고, 깜빡임 · 입 벌림은 0 으로 둔다.
// 결과적으로 '머리 이동' 조건은 늘 통과하고 움직임 간섭도 잡히지 않는다 — 비교할 때 이 점을 밝힌다.
import { createInterface } from 'node:readline';
import { createReadStream } from 'node:fs';
import { analyze, SPEC_OPTS, SEARCH_BAND } from '../../src/pipeline/index.js';

// 실험용 조정 (비워 두면 앱이 쓰는 값 그대로)
//   SUBHARM=off        서맥 보정을 끈다
//   SUBHARM_RATIO=0.4  서맥 보정이 걸리는 세기 문턱
//   HARMONICS=2        고조파 합에 쓰는 개수
//   BAND_HI=3.3        bpm 탐색 대역 위끝 (Hz)
if (process.env.SUBHARM === 'off') SPEC_OPTS.subharmonic = null;
else if (process.env.SUBHARM_RATIO) SPEC_OPTS.subharmonic = { ...SPEC_OPTS.subharmonic, ratio: +process.env.SUBHARM_RATIO };
if (process.env.HARMONICS) SPEC_OPTS.harmonics = +process.env.HARMONICS;
if (process.env.BAND_HI) SEARCH_BAND[1] = +process.env.BAND_HI;
if (process.env.BAND_LO) SEARCH_BAND[0] = +process.env.BAND_LO;

const FACE_W = 200, FACE_C = [320, 240];

function toSamples(t, roi) {
  const out = new Array(t.length);
  for (let i = 0; i < t.length; i++) {
    const [fh, lc, rc] = roi[i];
    const brightness = (fh[0]+fh[1]+fh[2] + lc[0]+lc[1]+lc[2] + rc[0]+rc[1]+rc[2]) / 9;
    out[i] = { t: t[i] * 1000, forehead: fh, lcheek: lc, rcheek: rc,
      faceWidth: FACE_W, faceCenter: FACE_C, brightness, blink: 0, mouthOpen: 0 };
  }
  return out;
}

const file = process.argv[2];
if (!file) { console.error('usage: node mcd_windows.mjs <windows.jsonl>'); process.exit(2); }
const rl = createInterface({ input: createReadStream(file), crlfDelay: Infinity });
for await (const line of rl) {
  if (!line.trim()) continue;
  const w = JSON.parse(line);
  let o;
  try {
    const r = analyze(toSamples(w.t, w.roi), { resp: false });
    const q = r.quality;
    o = { key: w.key, bpm: r.bpm, snr: r.snrDb, pass: !!q.pass, reason: q.reason,
      method: r.method, windowed: !!r.window,
      hrv_ok: r.hrvReliable === true, rmssd: Number.isFinite(r.rmssd) ? r.rmssd : null,
      bright_ok: !!q.brightnessOk, snr_ok: !!q.snrOk, cov_ok: !!q.coverageOk,
      itf_ok: !!q.interferenceOk, roi_ok: !!q.roiAgreeOk };
  } catch (e) {
    o = { key: w.key, error: String(e && e.message || e) };
  }
  process.stdout.write(JSON.stringify(o) + '\n');
}
