// Area 2: illumination. node scripts/robustness/02_illum.js
import { sweep, STD_HEADER, stdRow } from './evalrun.js';
import { table } from './gen.js';
const N = +process.env.N || 30;
const cells = [
  ['기준', {}],
  ['AE 스텝 1회 5%', { expoSteps: 1, expoStepMag: 0.05 }], ['AE 스텝 1회 10%', { expoSteps: 1, expoStepMag: 0.1 }],
  ['AE 스텝 1회 20%', { expoSteps: 1, expoStepMag: 0.2 }], ['AE 스텝 3회 10%', { expoSteps: 3, expoStepMag: 0.1 }],
  ['AE 스텝 3회 20%', { expoSteps: 3, expoStepMag: 0.2 }],
  ['WB 채널별 드리프트 3%', { wbDrift: 0.03 }], ['WB 채널별 드리프트 10%', { wbDrift: 0.1 }],
  ['조명 드리프트 강함(0.15)', { drift: 0.15 }],
  ['120Hz 깜빡임 2% @30fps (alias 0Hz)', { flickerHz: 120, flickerAmp: 0.02 }],
  ['120Hz 2% @29.5fps (alias 2Hz=120bpm)', { flickerHz: 120, flickerAmp: 0.02, fps: 29.5 }],
  ['120Hz 0.5% @29.5fps', { flickerHz: 120, flickerAmp: 0.005, fps: 29.5 }],
  ['100Hz 2% @24fps (alias 4Hz)', { flickerHz: 100, flickerAmp: 0.02, fps: 24 }],
  ['100Hz 2% @29.97fps (alias ~10Hz)', { flickerHz: 100, flickerAmp: 0.02, fps: 29.97 }],
  ['100Hz 0.5% @24.5fps (alias 2Hz)', { flickerHz: 100, flickerAmp: 0.005, fps: 24.5 }],
  ['120Hz 2% chroma30% @29.5fps (alias 2Hz)', { flickerHz: 120, flickerAmp: 0.02, flickerChroma: 0.3, fps: 29.5 }],
  ['120Hz 0.5% chroma30% @29.5fps', { flickerHz: 120, flickerAmp: 0.005, flickerChroma: 0.3, fps: 29.5 }],
  ['100Hz 2% chroma30% @24.5fps (alias 2Hz)', { flickerHz: 100, flickerAmp: 0.02, flickerChroma: 0.3, fps: 24.5 }],
  ['100Hz 2% chroma30% @30fps (alias 10Hz)', { flickerHz: 100, flickerAmp: 0.02, flickerChroma: 0.3 }],
  ['화면광 1.3Hz 0.3%', { screenHz: 1.3, screenAmp: 0.003 }], ['화면광 1.3Hz 1%', { screenHz: 1.3, screenAmp: 0.01 }],
  ['화면광 2.2Hz 1%', { screenHz: 2.2, screenAmp: 0.01 }],
];
table('2. 조명 (REAL 프로필)', STD_HEADER, cells.map(([l, c]) => stdRow(l, sweep(c, N))));
