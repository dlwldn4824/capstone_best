// 호흡수(참고값). 숨 쉴 때 생기는 머리의 상하 움직임과 얼굴 밝기의 느린 변화를 0.13–0.5Hz(8–30회/분)에서 찾는다.
// 두 후보가 ±2회/분 안에서 맞고, 둘 다 평평한 스펙트럼 바닥(대역 중앙값)보다 뚜렷이 높을 때만 값을 낸다. 아니면 NaN.
// 호흡 성분이 없을 때도 '가장 큰 봉우리'는 늘 있으므로, 합의·돌출 조건 없이 값을 내면 그럴듯한 거짓 값이 나온다.
import { bandpass } from './filter.js';
import { fft, nextPow2 } from './spectrum.js';
import { toUniform, GRID_FS } from './resample.js';

export const RESP_BAND = [0.13, 0.5];
// prominence 10: 호흡 없는 입력에서 값 표시 3–5%, 호흡 15/분 입력에서 77% (scripts/robustness 측정, 6이면 17% / 92%)
export const RESP = { agreeBpm: 2, prominence: 10, edgeHz: 0.02 };

// 대역 안 주기도에서 '대역 끝이 아닌' 가장 높은 국소 최대. 반환 { rate(회/분), prom(최고점/대역 중앙값) }
// 느린 조명 드리프트가 대역 하한으로 새어 들어오면 전역 최대는 끝에 붙으므로, 끝 봉우리는 호흡으로 보지 않는다.
function respPeak(x, fs) {
  const y = bandpass(x, fs, RESP_BAND[0], RESP_BAND[1]);
  const n = y.length, nfft = Math.max(8192, nextPow2(n) * 4);
  const re = new Float64Array(nfft), im = new Float64Array(nfft);
  let m = 0; for (const v of y) m += v; m /= n;
  for (let i = 0; i < n; i++) re[i] = (y[i] - m) * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)));
  fft(re, im);
  const f = [], p = [];
  for (let k = 0; k <= nfft / 2; k++) {
    const hz = k * fs / nfft;
    if (hz < RESP_BAND[0] || hz > RESP_BAND[1]) continue;
    f.push(hz); p.push(re[k] * re[k] + im[k] * im[k]);
  }
  let bi = -1;
  for (let i = 1; i < p.length - 1; i++) {
    if (f[i] - RESP_BAND[0] < RESP.edgeHz || RESP_BAND[1] - f[i] < RESP.edgeHz) continue;
    if (p[i] >= p[i - 1] && p[i] >= p[i + 1] && (bi < 0 || p[i] > p[bi])) bi = i;
  }
  if (bi < 0) return { rate: NaN, prom: 0 };
  const sorted = [...p].sort((a, b) => a - b), med = sorted[sorted.length >> 1] || 1e-30;
  return { rate: f[bi] * 60, prom: p[bi] / med };
}

// samples: Sample[] (타임스탬프 기준으로 내부에서 균일화하므로 fs 인자는 무시해도 된다)
// → { rate: 회/분 | NaN, agree: boolean, snrDb (돌출도 dB, 하위 호환), head, light }
export function respFromSamples(samples, _fs) {
  const none = { rate: NaN, agree: false, snrDb: -Infinity, head: NaN, light: NaN };
  if (samples.length < 2 || (samples[samples.length - 1].t - samples[0].t) / 1000 < 15) return none;
  const { rows } = toUniform(samples, GRID_FS);
  const head = respPeak(rows.map(s => s.faceCenter[1] / Math.max(s.faceWidth, 1)), GRID_FS);
  const light = respPeak(rows.map(s => (s.forehead[1] + s.lcheek[1] + s.rcheek[1]) / 3), GRID_FS);
  const agree = Math.abs(head.rate - light.rate) <= RESP.agreeBpm
    && head.prom >= RESP.prominence && light.prom >= RESP.prominence;
  const snrDb = 10 * Math.log10(Math.min(head.prom, light.prom));
  return { rate: agree ? (head.rate + light.rate) / 2 : NaN, agree, snrDb: agree ? snrDb : -Infinity, head: head.rate, light: light.rate };
}
