// 결과 화면에 무엇을 어떻게 보여 줄지 정하는 순수 함수. DOM 을 모른다 (tests/view.test.js).
//
// 규칙
//   얼굴 샘플이 거의 없음          → noface: 숫자 없이 다시 재기 안내
//   품질 기준 미달                → retry : 심박 · 박동 간격 · 호흡은 '–'. 깜빡임 · 머리 흔들림은 관측값이라 보여 준다 (왜 실패했는지 보는 데 쓴다)
//   품질 통과                    → ok    : 심박 · 맥파 표시. 박동 간격은 hrvReliable 일 때만 '참고', 호흡은 두 주기가 맞을 때만 '참고'
//   숫자가 생리적으로 말이 안 되면   → 보류  (RMSSD > 200 ms, 호흡 8–30회/분 밖)
//   깜빡임은 얼굴이 실제로 잡혀 있던 시간(f.durationSec)이 20초 이상일 때만
//   값이 '–' 이면 단위를 붙이지 않는다 (hr.unit 도 같은 규칙)
//   빠르게 잰 스캔(mode 'quick', 25초 미만)에서 빠진 항목은 '전체 측정에서 볼 수 있어요'
//   평소값(base)을 같이 넘기면 view.deviation 에 '평소와 얼마나 다른가'가 담긴다. 이 앱이 하려는 말이 그것이다.
//   흔들린 구간을 빼고 일부만 쓴 스캔(r.window)은 품질 표에 '쓴 구간'을 적고, 박동 간격 · 호흡 보류 이유도 그렇게 말한다
import { REASON_TEXT } from '../pipeline/quality.js';
import { deviationOf } from '../pipeline/baseline.js';

const ok = v => v != null && Number.isFinite(v);
const fmt = (v, d = 0) => (ok(v) ? v.toFixed(d) : '–');
export const SIGNAL_GOOD_DB = 10;   // hrvReliable 과 같은 기준: 이 위에서만 '신호 좋음'

export function resultView(scan, base = null) {
  const r = scan?.r, f = scan?.f;
  // 빠르게 잰 스캔(30초 전에 끝남)에서 박동 간격 · 호흡 · 깜빡임이 빠지면 "전체 측정"으로 안내한다
  const short = scan?.mode === 'quick' && r && r.durationSec < 25;
  if (!r) return { status: 'noface', title: '얼굴이 거의 잡히지 않았어요', message: '휴대폰을 세워 두고, 원 안에 얼굴이 들어오게 한 뒤 다시 해 주세요.', tiles: [], quality: [] };

  const q = r.quality, pass = !!q.pass;
  const windowed = !!r.window;        // 전체가 아니라 깨끗한 구간만 써서 나온 값
  const view = {
    status: pass ? 'ok' : 'retry',
    title: pass ? null : '다시 재 볼까요?',
    message: pass ? null : (REASON_TEXT[q.reason] || '맥박 신호를 충분히 모으지 못했어요.'),
    signal: !pass ? { label: '기준 미달', tone: 'warn' } : r.snrDb >= SIGNAL_GOOD_DB ? { label: '신호 좋음', tone: 'good' } : { label: '신호 보통', tone: '' },
    hr: { value: pass ? fmt(r.bpm) : '–', unit: pass ? 'bpm' : '', shown: pass },
    wave: pass,
    tiles: [],
    quality: qualityRows(r),
    deviation: deviationFor(r, base, pass),
  };

  const hrvOk = pass && r.hrvReliable === true && ok(r.rmssd) && r.rmssd > 0 && r.rmssd <= 200;
  view.tiles.push({ key: 'hrv', label: '박동 간격 흔들림', value: hrvOk ? fmt(r.rmssd) : '–', unit: hrvOk ? 'ms' : '', state: hrvOk ? 'ref' : 'held',
    sub: hrvOk ? `박동 간격 ${r.hrvPairs ?? r.rr.length}쌍` : pass ? (windowed ? '흔들리지 않은 구간만 써서 보류했어요' : short ? '전체 측정에서 볼 수 있어요' : '신호가 약해 보류했어요') : '다시 재면 볼 수 있어요' });

  const rate = r.resp?.rate, respOk = pass && ok(rate) && rate >= 8 && rate <= 30;
  view.tiles.push({ key: 'resp', label: '호흡', value: respOk ? fmt(rate) : '–', unit: respOk ? '회/분' : '', state: respOk ? 'ref' : 'held',
    sub: respOk ? '머리 · 밝기 주기 일치' : pass ? (windowed ? '흔들리지 않은 구간만 써서 보류했어요' : short ? '전체 측정에서 볼 수 있어요' : '호흡 주기가 안 잡혔어요') : '다시 재면 볼 수 있어요' });

  const blinkOk = f && f.durationSec >= 20 && ok(f.blinkPerMin);
  view.tiles.push({ key: 'blink', label: '눈 깜빡임', value: blinkOk ? fmt(f.blinkPerMin) : '–', unit: blinkOk ? '회/분' : '', state: blinkOk ? 'ok' : 'held',
    sub: blinkOk ? `${Math.round(f.durationSec)}초 동안 ${f.blinks}번` : short ? '전체 측정에서 볼 수 있어요' : '얼굴이 잡힌 시간이 짧았어요' });

  const headOk = f && ok(f.headMovePct);
  view.tiles.push({ key: 'head', label: '머리 흔들림', value: headOk ? fmt(f.headMovePct, 1) : '–', unit: headOk ? '%' : '', state: headOk ? 'ok' : 'held',
    sub: headOk ? (f.headMovePct < 1 ? '가만히 잘 있었어요' : f.headMovePct < 2.5 ? '조금 움직였어요' : '많이 움직였어요') : '' });

  return view;
}

// 평소와 비교한 한 줄. 품질을 통과한 스캔에만 붙인다 (떨어진 값으로 평소를 말하면 안 된다).
function deviationFor(r, base, pass) {
  if (!pass || !base) return { level: 'none', text: '', diff: NaN, need: 0 };
  if (!base.ready) return { level: 'learning', text: `평소를 알려면 ${base.need}번 더 재면 돼요`, diff: NaN, need: base.need };
  const d = deviationOf(r.bpm, base);
  const n = Math.abs(Math.round(d.diff));
  const text = d.level === 'same' ? '평소와 비슷해요' : d.level === 'high' ? `평소보다 ${n} bpm 높아요` : `평소보다 ${n} bpm 낮아요`;
  return { level: d.level, text, diff: d.diff, baseBpm: base.bpm, need: 0 };
}

function qualityRows(r) {
  const q = r.quality, pct = v => `${fmt(v * 100)}%`;
  // 샘플이 8초 분량도 안 되면 개별 비율은 계산하지 않았다 → 얼굴이 잡힌 시간만 보여 준다
  if (q.short) return [{ label: '얼굴이 잡힌 시간', value: r.coverage ? pct(r.coverage.ratio) : '–', ok: false }];
  const rows = [
    { label: '밝기가 알맞았던 시간', value: pct(q.brightnessRatio), ok: q.brightnessOk },
    { label: '머리가 가만히 있던 시간', value: pct(q.motionRatio), ok: q.motionOk },
    { label: '눈 감기 · 말하기', value: pct(q.blinkRatio), ok: q.blinkOk },
    { label: '맥박 신호 대 잡음', value: `${fmt(r.snrDb, 1)} dB`, ok: q.snrOk },
  ];
  if (r.coverage) rows.push({ label: '얼굴이 잡힌 시간', value: pct(r.coverage.ratio), ok: q.coverageOk });
  if (r.window) rows.push({ label: '쓴 구간', value: `${fmt(r.window.startSec)}–${fmt(r.window.endSec)}초`, ok: true });
  if (q.interferenceOk != null) rows.push({ label: '화면 깜빡임 · 끄덕임', value: q.interferenceOk ? '없음' : '섞임', ok: q.interferenceOk });
  if (q.roiAgreeOk != null) rows.push({ label: '이마 · 볼 심박 일치', value: `${r.roiAgree ?? '–'}/3`, ok: q.roiAgreeOk });
  return rows;
}
