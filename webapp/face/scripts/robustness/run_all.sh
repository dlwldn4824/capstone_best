#!/bin/sh
# Reproduce every robustness table. Usage: sh scripts/robustness/run_all.sh > scripts/robustness/results_after.md
cd "$(dirname "$0")/../.." || exit 1
for f in 01_timing 02_illum 03_motion 04_amplitude 05_harmonic 06_hrv 07_retest 08_irregular 09_resp 10_quick 11_key 12_hrv_gate; do
  node "scripts/robustness/$f.js"
done
