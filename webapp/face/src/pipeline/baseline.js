// 평소값. 이 앱이 하려는 말은 "지금 심박이 몇이다"가 아니라 "평소와 다른가"다.
//
// 왜 심박인가 (docs/research/HRV_VERDICT.md): WESAD 에서 같은 사람·같은 시각에 가슴 ECG 와 손목 PPG 를 같이 재 보니
// 스트레스 때 심박은 15명 전원이 올랐고(+21 bpm, p=0.0001) ECG 와 거의 같았다. 반면 HRV(RMSSD)는 손목에서 3.6배
// 부풀려져 실제 변화(-13 ms)가 묻혔다. 그래서 박동 간격이 아니라 심박으로 말한다.
//
// 왜 절대값이 아니라 이탈인가 (docs/research/RISK_MODEL.md): 공개 데이터로 학습한 위험 모델도 평소 대비 이탈(night_z)과
// 최근 3일 중 이탈일 수(dev3)를 쓴다. 심박 '한 번의 값'은 사람마다 달라 그 자체로는 아무 말도 못 한다.

export const BASELINE = {
  minScans: 5,        // 이만큼 쌓이기 전에는 평소를 말하지 않는다
  z: 2,               // 평소 흩어짐의 몇 배부터 '다르다'고 할지
  minDiffBpm: 5,      // 이보다 작은 차이는 측정 오차 안이다 (POS 평균 오차 3.7–4.5 bpm) → '평소와 같아요'
  window: 30,         // 최근 몇 번까지 평소값에 쓸지
};

const median = a => { const s = [...a].sort((x, y) => x - y); const i = s.length >> 1; return s.length % 2 ? s[i] : (s[i - 1] + s[i]) / 2; };

// 품질을 통과한 지난 스캔만 쓴다. scans: [{ ts, r }] (최신순이든 아니든 상관없음)
export function baselineOf(scans, rule = BASELINE) {
  const bpms = (scans || [])
    .filter(s => s?.r?.quality?.pass && Number.isFinite(s.r.bpm))
    .sort((a, b) => b.ts - a.ts)
    .slice(0, rule.window)
    .map(s => s.r.bpm);
  if (bpms.length < rule.minScans) return { ready: false, n: bpms.length, need: rule.minScans - bpms.length, bpm: NaN, spread: NaN };
  const m = median(bpms);
  // 중앙값 절대편차 → 표준편차 환산(1.4826). 한두 번 크게 튄 값에 평소가 끌려가지 않게 한다.
  const spread = Math.max(median(bpms.map(v => Math.abs(v - m))) * 1.4826, 0);
  return { ready: true, n: bpms.length, need: 0, bpm: m, spread };
}

// 이번 스캔이 평소와 다른가. base 가 아직 준비 안 됐으면 level 'unknown'.
export function deviationOf(bpm, base, rule = BASELINE) {
  if (!base?.ready || !Number.isFinite(bpm)) return { level: 'unknown', diff: NaN, cut: NaN };
  const diff = bpm - base.bpm;
  const cut = Math.max(rule.minDiffBpm, rule.z * base.spread);
  return { level: diff >= cut ? 'high' : diff <= -cut ? 'low' : 'same', diff, cut };
}

// 이유. '짚이는 게 없음'(none)만 쌓이는 쪽으로 간다.
export const WHY = [
  { key: 'exercise', label: '움직였어요' },
  { key: 'caffeine', label: '커피 마셨어요' },
  { key: 'sleep', label: '잠이 모자라요' },
  { key: 'tense', label: '긴장했어요' },
  { key: 'sick', label: '몸이 안 좋아요' },
  { key: 'none', label: '짚이는 게 없어요' },
];
export const WHY_LABEL = Object.fromEntries(WHY.map(w => [w.key, w.label]));

// 설명되지 않은 변화만 센다. 날짜별로 하나라도 있으면 그 날을 셈한다 (RISK_MODEL 의 dev3 와 같은 틀).
export function unexplained(scans, rule = BASELINE) {
  const base = baselineOf(scans, rule);
  if (!base.ready) return { ready: false, days: [], streak: 0, recent: 0 };
  const days = new Map();
  for (const s of scans || []) {
    if (!s?.r?.quality?.pass) continue;
    const lv = deviationOf(s.r.bpm, base, rule).level;
    const key = new Date(s.ts).toDateString();
    const hit = (lv === 'high' || lv === 'low') && s.why === 'none';
    days.set(key, (days.get(key) || false) || hit);
  }
  const ordered = [...days.entries()].sort((a, b) => new Date(b[0]) - new Date(a[0]));
  let streak = 0;
  for (const [, hit] of ordered) { if (!hit) break; streak++; }
  return { ready: true, days: ordered, streak, recent: ordered.slice(0, 3).filter(([, h]) => h).length };
}
