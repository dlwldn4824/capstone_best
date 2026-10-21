// Part 1b: does any compensation method manufacture a PASS when there is no pulse at all? node scripts/experiments/p1b_nopulse.js
import { scan, SEEDS, bpmFor } from './motion.js';
import { METHODS } from './p1_motion.js';
import { table, frac, pct } from '../robustness/gen.js';
const N = +process.env.N || 30;
const cells = [['still', 1, 'ideal'], ['nod', 1, 'ideal'], ['walk', 1, 'ideal'], ['nod', 1, 'hard'], ['combo', 2, 'hard']];
const data = cells.map(([sc, lv, obs]) => SEEDS(N).map((seed, i) => scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: lv, obs, noPulse: true }).samples));
table(`P1b 맥 없음(noPulse) 입력에서 PASS율 = 거짓 PASS (n=${N})`, ['방법', ...cells.map(c => `${c[0]}×${c[1]} ${c[2]}`)],
  METHODS.map(([l, fn]) => [l, ...data.map(d => pct(frac(d, s => fn(s).quality.pass)))]));
