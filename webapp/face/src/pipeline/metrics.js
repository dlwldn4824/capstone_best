// face 파이프라인 결과(Result) → /check 서버(webapp/check.py)가 받는 metrics.
// 키와 뜻은 check.py 의 METRIC_KEYS 를 따른다. 두 앱이 같은 숫자를 뜻하게 맞추는 자리다.
//
// 바뀐 점 (vitals.js 대비): HRV 는 face 의 문턱(SNR ≥ 10 dB · 이웃 쌍 ≥ 20)을 넘을 때만 보낸다.
// 합성 감사에서 그 아래 구간은 RMSSD 가 위로 편향됐다 (webapp/face/src/pipeline/index.js HRV_GATE).
import { HRV_GATE } from './index.js';

// Baevsky SI → 0–100. vitals.js 의 stressScore 와 같은 식이라 지난 기록과 같은 축에 놓인다.
export const SI_LO = 50, SI_HI = 1000;   // vitals.js 와 같은 값이어야 지난 기록과 같은 축이 된다
const r1 = v => (v == null || !Number.isFinite(v) ? null : Math.round(v * 10) / 10);
export const stressScore = si => (si == null || !Number.isFinite(si) || si <= 0 ? null
  : r1(Math.max(0, Math.min(1, (Math.log(si) - Math.log(SI_LO)) / (Math.log(SI_HI) - Math.log(SI_LO)))) * 100));
export const stressZone = s => (s == null ? null : s < 30 ? '편안' : s < 60 ? '보통' : s < 80 ? '높음' : '매우 높음');

// 신호 등급: vitals.js 와 같은 선(3 dB · 0 dB). 품질에 떨어진 측정은 'low' 로 내린다.
export function signalOf(snrDb, pass) {
  if (!Number.isFinite(snrDb) || !pass) return 'low';
  return snrDb >= 3 ? 'high' : snrDb >= 0 ? 'mid' : 'low';
}

export function toMetrics(r) {
  const pass = !!r?.quality?.pass;
  const signal = signalOf(r?.snrDb, pass);
  const hrvOk = pass && r.hrvReliable === true;
  const si = hrvOk ? r.baevskySI : null;
  const respOk = pass && r.resp?.agree === true && Number.isFinite(r.resp.rate);
  return {
    hr: pass ? r1(r.bpm) : null,
    snr: r1(r.snrDb),
    signal,
    rmssd: hrvOk ? r1(r.rmssd) : null,
    sdnn: hrvOk ? r1(r.sdnn) : null,
    pnn50: hrvOk ? r1(r.pnn50) : null,
    si: r1(si),
    stress: stressScore(si),
    // face 는 HRV 를 문턱 위에서만 쓴다 → 'mid' 라는 애매한 등급을 만들지 않는다
    hrv_conf: hrvOk ? 'high' : 'low',
    // 박동 간격의 급변(부정맥 의심)은 face 가 계산하지 않는다. 없는 값을 지어내지 않는다.
    irregular: null,
    rr: respOk ? r1(r.resp.rate) : null,
    rr_conf: respOk ? 'high' : 'low',
  };
}

export { HRV_GATE };
