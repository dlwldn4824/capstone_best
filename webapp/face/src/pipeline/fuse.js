// 창별 ROI 융합: 6초 창(1초 간격)마다 각 후보 맥파(합친 RGB · 이마 · 양 볼)의 SNR을 재고, SNR 비율로 가중해 더한 뒤
// Hann 창으로 겹쳐 잇는다. 스캔 전체에서 가장 좋은 ROI 하나만 고르는 것보다 움직임 구간마다 덜 흔들린 영역이 이긴다.
// 근거: DistancePPG(Kumar 2015, 영역별 품질 가중 결합) · scripts/experiments/p1_motion.js (방법 C/G2)
import { estimateBpm } from './spectrum.js';

function std(a) {
  let m = 0; for (const v of a) m += v; m /= a.length || 1;
  let s = 0; for (const v of a) s += (v - m) * (v - m);
  return Math.sqrt(s / (a.length || 1));
}

// pulses: 같은 길이의 맥파 배열들, fs: Hz. 반환: 융합한 맥파(Float32Array)
export function fuseWindows(pulses, fs, band, specOpts, winSec = 6) {
  const n = pulses[0].length, l = Math.min(n, Math.round(winSec * fs)), hop = Math.max(1, Math.round(fs));
  const out = new Float32Array(n), ws = new Float32Array(n);
  for (let t = 0; ; t += hop) {
    const t0 = Math.min(t, n - l);
    const seg = pulses.map(p => p.subarray(t0, t0 + l));
    const wt = seg.map(s => {
      const sd = std(s);
      if (!(sd > 0)) return { w: 0, sd: 1 };
      const e = estimateBpm(s, fs, band, 1024, specOpts);
      return { w: Number.isFinite(e.snrDb) ? 10 ** (e.snrDb / 10) : 0, sd };
    });
    for (let i = 0; i < l; i++) {
      const hw = 0.5 - 0.5 * Math.cos(2 * Math.PI * (i + 0.5) / l);
      let v = 0; for (let r = 0; r < seg.length; r++) v += wt[r].w * seg[r][i] / wt[r].sd;
      out[t0 + i] += hw * v; ws[t0 + i] += hw;
    }
    if (t0 === n - l) break;
  }
  for (let i = 0; i < n; i++) if (ws[i] > 0) out[i] /= ws[i];
  return out;
}
