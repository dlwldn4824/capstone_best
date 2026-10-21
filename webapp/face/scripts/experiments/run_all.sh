#!/bin/sh
# Reproduce every experiment table (synthetic only). Usage: sh scripts/experiments/run_all.sh   (~10 min on a laptop)
cd "$(dirname "$0")/../.." || exit 1
D=scripts/experiments
node $D/00_sanity.js                                   > $D/results_00_sanity.md
N=30 OBS=ideal node $D/p1_motion.js                    > $D/results_p1_ideal.md
N=30 OBS=hard  node $D/p1_motion.js                    > $D/results_p1_hard.md
P1_SKIP=1 N=30 node $D/p1b_nopulse.js                  > $D/results_p1b_nopulse.md
P1_SKIP=1 N=30 node $D/p1c_risk.js                     > $D/results_p1c_risk.md
P1_SKIP=1 N=40 M=A,G2 node $D/p2_window.js             > $D/results_p2a_window.md
P1_SKIP=1 N=40 M=A,G2 node $D/p2_earlystop.js          > $D/results_p2b_earlystop.md
N=40 node $D/p2_lost.js                                > $D/results_p2c_lost.md
N=20 node $D/p3_gate.js                                > $D/results_p3_gate.md
P1_SKIP=1 N=40 M=A,G2 CELLS=still:1,combo:1,nod:1 EXTRA='{"amp":0.4,"noise":0.6}' node $D/p2_earlystop.js > $D/results_p2b_earlystop_weak.md
