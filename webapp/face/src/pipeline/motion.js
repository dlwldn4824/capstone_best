// 움직임 상쇄: 얼굴 위치 · 크기(랜드마크에서 온 faceCenter · faceWidth)와 그 변화율을 참조 신호로 두고
// NLMS 적응 필터로 맥파에서 움직임과 같이 움직이는 성분을 뺀다. 앞뒤로 한 번씩 돌려 평균(위상 지연 없음).
//
// 항상 쓰지 않는다. 박동 때문에 머리가 미세하게 흔들리면(BCG) 참조 신호에 맥박이 섞여 진짜 맥박까지 지운다
// (scripts/experiments/results_p1c_risk.md: BCG 1px 에서 품질 통과 3%). 그래서 analyze() 는 품질 미달인 스캔에만 다시 돌려 본다.
import { bandpass } from './filter.js';

function std(a) {
  let m = 0; for (const v of a) m += v; m /= a.length || 1;
  let s = 0; for (const v of a) s += (v - m) * (v - m);
  return Math.sqrt(s / (a.length || 1));
}

// rows: 균일 격자 Sample[] → 참조 신호 8개 (맥파와 같은 대역으로 거름)
export function motionRefs(rows, fs, pulseBand) {
  const x = rows.map(s => s.faceCenter[0] / Math.max(s.faceWidth, 1));
  const y = rows.map(s => s.faceCenter[1] / Math.max(s.faceWidth, 1));
  const w = rows.map(s => Math.log(Math.max(s.faceWidth, 1)));
  const lp = a => bandpass(Float32Array.from(a), fs, 0.05, 6);             // 직류만 빼고 모양은 남긴다
  const X = lp(x), Y = lp(y), Wd = lp(w);
  const d = a => Float32Array.from(a, (v, i) => (a[Math.min(a.length - 1, i + 1)] - a[Math.max(0, i - 1)]) * fs / 2);
  const sq = a => { const s = std(a) || 1; return Float32Array.from(a, v => (v / s) ** 2); };
  return [X, Y, Wd, d(X), d(Y), d(Wd), sq(X), sq(Y)].map(r => bandpass(r, fs, pulseBand[0], pulseBand[1]));
}

export function nlmsCancel(y, refs, mu = 0.02) {
  const run = (yy, rr) => {
    const n = yy.length, k = rr.length, w = new Float64Array(k), out = new Float32Array(n);
    const sc = rr.map(r => std(r) || 1);
    for (let i = 0; i < n; i++) {
      let yh = 0, pw = 1e-9;
      for (let a = 0; a < k; a++) { const v = rr[a][i] / sc[a]; yh += w[a] * v; pw += v * v; }
      const e = yy[i] - yh; out[i] = e;
      for (let a = 0; a < k; a++) w[a] += mu * e * rr[a][i] / sc[a] / pw;
    }
    return out;
  };
  const rev = a => Float32Array.from(a).reverse();
  const fwd = run(y, refs), bwd = rev(run(rev(y), refs.map(rev)));
  return Float32Array.from(fwd, (v, i) => (v + bwd[i]) / 2);
}
