// 측정 기준 상수와 설계 문서(docs/app/FACE_DESIGN.md)의 숫자가 같은지 본다.
// 문서에 적힌 기준값을 바꾸고 문서를 그대로 두면 여기서 실패한다. 실패 메시지에 나온 문장으로 문서를 고치면 된다.
// 다른 줄에 같은 숫자가 있어도 통과하지 않도록 기준이 적힌 줄을 통째로 맞춰 본다.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { QUALITY, ROBUST } from '../src/pipeline/quality.js';
import { EARLY_STOP, WINDOW } from '../src/pipeline/index.js';
import { GRID_FS } from '../src/pipeline/resample.js';
import { FRAMING } from '../src/capture/framing.js';

const DOC = fileURLToPath(new URL('../../../docs/app/FACE_DESIGN.md', import.meta.url));
const doc = readFileSync(DOC, 'utf8');
const n = v => `${+(v * 100).toFixed(1)}`;   // 0.05 → 5, 0.035 → 3.5 (반올림으로 바뀐 값을 놓치지 않게)
const pct = v => `${n(v)}%`;

const expected = {
  QUALITY: [
    `4조건은 **밝기 ${QUALITY.brightnessMin}–${QUALITY.brightnessMax} ≥ ${pct(QUALITY.brightnessRatioMin)}, `
      + `움직임 < 얼굴폭 ${pct(QUALITY.motionFrac)} ≥ ${pct(QUALITY.motionRatioMin)}, `
      + `깜빡임·말하기 < ${pct(QUALITY.blinkRatioMax)}, SNR ≥ ${QUALITY.snrMinDb} dB** 다.`,
    `샘플이 ${QUALITY.minSamples / GRID_FS}초 분량 미만이면`,
  ],
  ROBUST: [
    `| coverage | 얼굴 잡힌 시간 ≥ ${pct(ROBUST.coverageRatioMin)}, 최대 놓침 ≤ ${ROBUST.maxGapSecMax} s |`,
    `| roi | 단일 ROI 3개 중 ${ROBUST.roiAgreeMin}개 이상이 ±${ROBUST.roiAgreeBpm} bpm 안 |`,
  ],
  WINDOW: [
    `| 구간 선택 | 전체가 떨어지면 ${WINDOW.sec}초 구간을 ${WINDOW.stepSec}초 간격으로 훑어, `
      + `같은 bpm(±${ROBUST.roiAgreeBpm})을 내는 구간이 ${WINDOW.agreeMin}개 이상일 때`,
  ],
  FRAMING: [
    `far/near(얼굴 폭 = 타원 폭의 ${n(FRAMING.sizeMin)}–${pct(FRAMING.sizeMax)}) → center(${pct(FRAMING.centerMax)}) → `
      + `angle(좌우·갸웃 ${FRAMING.yawMax}°, 위아래 ${FRAMING.pitchMax}°, MediaPipe 변환 행렬) → `
      + `dark/bright(${FRAMING.lightMin}–${FRAMING.lightMax}) → shake(0.5초 코끝 ${pct(FRAMING.shakeMax)})`,
  ],
  EARLY_STOP: [
    `빠르게 = 최근 ${EARLY_STOP.windowSec}초 실시간 추정 ${EARLY_STOP.K}번이 ±${EARLY_STOP.tolBpm} bpm 안 · `
      + `SNR ≥ ${EARLY_STOP.snrDbMin} dB · ${EARLY_STOP.minSec}초 이상 · 전체 품질 통과면 끝(최대 ${EARLY_STOP.maxSec}초`,
  ],
};

describe('측정 기준 ↔ docs/app/FACE_DESIGN.md', () => {
  it('좌우와 갸웃 한계가 같아 문서에 한 숫자로 적는다', () => {
    expect(FRAMING.rollMax).toBe(FRAMING.yawMax);
  });

  for (const [name, lines] of Object.entries(expected)) {
    it(`${name} 를 바꾸면 문서도 고친다`, () => {
      const missing = lines.filter(l => !doc.includes(l));
      expect(missing, `FACE_DESIGN.md 에 이 문장이 없다`).toEqual([]);
    });
  }
});
