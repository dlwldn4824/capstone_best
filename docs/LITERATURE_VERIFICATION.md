# 선행연구 수치 검증

계획 문서에 적힌 논문·데이터·수치를 원문/출판사 페이지와 대조한 결과.
검증일 2026-09-05.

범례 — **확인**: 원문 또는 출판사 페이지에서 직접 확인 · **미확인**: 논문은
존재하나 해당 수치를 확인하지 못함 · **찾지 못함**: 논문 자체를 찾지 못함

---

## 요약

| 논문 | 존재 | 인용 수치 | 조치 |
| --- | --- | --- | --- |
| Mishra 2020 (Nat Biomed Eng) | 확인 | 대부분 확인 | 그대로 사용 |
| Quer 2021 (Nat Med) | 확인 | 정확히 일치 | 그대로 사용 |
| Hongn 2025 (Sci Data) | 확인 | 확인 + **중요한 누락 발견** | 아래 참조 |
| Gabrielli (AIiM) | 확인 | F1 수치 미확인 | 원문 확인 후 인용 |
| **Li 2026 (Sensors)** | **찾지 못함** | — | **인용 보류** |
| Ibrahim 2026 (Sci Rep) | 확인 | AUC 미확인 | 원문 확인 후 인용 |
| Kim 2026 (IEEE TCE) | 확인 | 94.8% 미확인 | 원문 확인 후 인용 |
| Norman 2026 (Auton Neurosci) | 확인 | 정성 주장만 | 그대로 사용 |

---

## 1. Mishra et al. 2020 — 확인

*Pre-symptomatic detection of COVID-19 from smartwatch data*,
Nature Biomedical Engineering **4**, 1208–1220 (2020). PMID 33208926.

| 계획 문서 | 검증 결과 |
| --- | --- |
| 코호트 약 5,262명 | 확인 ("nearly 5,300") |
| COVID 감염자 32명 | 확인 |
| 26/32 (81%) 에서 변화 탐지 | 확인 |
| 25명 중 22명이 증상 발생 전/당일 | 확인 |
| 4명은 최소 9일 전 | 확인 |
| 실시간 알고리즘으로 63% 사전 탐지 | **미확인** — 원문 재확인 필요 |

## 2. Quer et al. 2021 — 확인

*Wearable sensor data and self-reported symptoms for COVID-19 detection*,
Nature Medicine (2021). PMID 33122860.

| 계획 문서 | 검증 결과 |
| --- | --- |
| 30,529명 등록 | 확인 (2020-03-25 ~ 06-07) |
| 3,811명 증상 보고 | 확인 |
| 양성 54 / 음성 279 | 확인 |
| 센서+증상 AUC 0.80 | 확인 (**IQR 0.73–0.86** — 이 구간도 함께 인용할 것) |
| 개별 AUC 0.52/0.68/0.69/0.72/0.71 | 미확인 — 표에서 재확인 |

## 3. Hongn et al. 2025 — 확인 + 계획 문서에 누락된 사항

*Wearable Physiological Signals under Acute Stress and Exercise Conditions*,
Scientific Data **12** (2025). PMID 40155406 / PMC11953403.
데이터: PhysioNet `wearable-device-dataset` v1.0.1 (Open Access,
압축 69.7 MB / 해제 247.4 MB).

확인된 것: 36 / 30 / 31명, Empatica E4, 49 feature (BVP 2 · HR 4 · HRV 20 ·
EDA 13 · ACC 10), 축소 feature 13 / 12 / 19개, XGBoost 93% / 91% / 84%,
80/20 split + 10-fold CV.

### 계획 문서가 놓친 것 (파이프라인에 직접 영향)

1. **프로토콜이 두 버전이다.**
   - v1 (S 코호트): 3분 baseline → Stroop → 5분 휴식 → TMCT → 5분 휴식 →
     Opinion → 1022에서 13씩 빼기
   - v2 (f 코호트): **Stroop 제거**, 두 번째 휴식을 Opinion 과 Subtract 사이로
     이동, 휴식에 이완 영상 추가, 원격 수행

   운동 프로토콜도 v1/v2 가 다르다 (Anaerobic: v1 = 30초 스프린트 3회 /
   v2 = 45초 4회). **하나의 태그 매핑으로 전체를 처리할 수 없다.**
   → `configs/protocol.yaml` 이 `version_by_prefix` 로 이를 처리한다.

2. **제외 대상 피험자.** 원 논문이 분류 실험에서 뺀 것은
   `f07`(손목밴드 보호 커버 미제거), `f13`(착용 불량) 두 명이다.
   → `configs/config.yaml` 의 `exclude.ml_excluded_subjects`.

3. **품질 이슈가 기록된 세션** (`data_constraints.txt`): S02 스트레스 중복,
   f14 스트레스 2분할, S03·S07 유산소 불완전, S11 유산소 2분할,
   S12 유산소 없음, S06 무산소 불완전, S16 무산소 2분할.
   → `exclude.flagged` 로 표시만 하고 제외하지는 않는다.

4. **세그먼트 선택 규칙.** 휴식 블록은 **후반부만**(잔여 스트레스 배제),
   유산소는 70·75·80·85 rpm 블록의 **중앙 1분**, 스프린트는 전체.
   → `protocol.yaml` 의 `portions` 필드.

5. **축소 feature 목록** (재현 시 그대로 쓸 것)
   - Stress/Rest 13개: `hr_mean, mean_raw_eda, mean_tonic_eda, std_tonic_eda,
     mean_recoverytime, max_ibi, ibi_mean, rmssd, ratio, LF_peak, x_std,
     y_std, z_std`
   - Aerobic/Sprint 12개: `hr_std, std_phasic_eda, tonic_ratio_down,
     peaks_density, mean_recoverytime, min_ibi, pnn50, VHF_power, LF_n,
     z_std, acc_mean, acc_ratio_down`
   - 4-class 19개: 위 둘의 합집합
   - 선택 방법: Pearson r > 0.8 상관 제거 + Sweetviz 탐색

6. **원 논문은 피험자를 분리하지 않았다.** 80/20 + 10-fold 라고만 되어 있고
   LOSO 라는 언급이 없다. 93% 를 우리 subject-independent 수치와 직접
   비교하면 안 된다.

## 4. Gabrielli et al. — 논문 확인, 수치 미확인

*Seamless Monitoring of Stress Levels Leveraging a Foundational Model for
Time Sequences*. Gabrielli, Prenkaj, Velardi (Sapienza / TU München).
arXiv:2407.03821, Artificial Intelligence in Medicine.

확인: DREAMER / MAHNOB-HCI / WESAD 세 벤치마크, UniTS 파인튜닝,
anomaly detection 으로 문제 정식화, "12개 최고 성능 방법을 상회",
침습적 신호와 경량 기기 신호에서 성능이 비슷함.

**미확인**: F1 0.869 / 0.878 / 0.834 / 0.856, 평균 0.859 ± 0.019,
피험자 수 23 / 27 / 15. → arXiv PDF 본문 표에서 직접 확인하고 인용할 것.

## 5. Li et al. 2026 (Sensors) — 찾지 못함 ⚠

*Neuro-Symbolic Class-Contrast Evidence Audit for Reliable Cross-Subject
Wearable Activity Recognition*.

제목·저자·지표(UCI HAR Accuracy 90.13%, Macro F1 90.55%, Error AUPRC
0.4238 → 0.4331)로 세 차례 검색했으나 해당 논문을 찾지 못했다.
MDPI Sensors 에서도 확인되지 않는다.

**조치**
- 이 인용은 **보류**한다. DOI 를 확보하기 전까지 발표 자료에 넣지 않는다.
- 우리 audit 구조의 근거로는 검색에서 확인된 다음을 대신 쓸 수 있다.
  - *Neuro-Symbolic Approaches for Context-Aware Human Activity Recognition*
    (arXiv:2306.05058) — semantic loss 로 context 지식을 HAR 분류기에 주입
  - *Semantic Loss: A New Neuro-Symbolic Approach for Context-Aware HAR*,
    Proc. ACM IMWUT 7(4), 2023 — 위의 저널 버전
- 다만 이 대체 논문들은 **분류 시점에 symbolic reasoning 을 쓰지 않고**
  학습 손실에 지식을 넣는 방식이라 우리 audit 구조와 다르다. 근거로 쓰려면
  차이를 명시해야 한다.

> **원 출처를 어디서 얻었는지 확인할 것.** 존재하지 않는 논문을 인용하면
> 심사에서 가장 먼저 지적된다.

## 6. Ibrahim 2026 — 논문 확인, 수치 미확인

*A causal discovery framework for digital phenotyping*,
Scientific Reports (2026), DOI `10.1038/s41598-026-55866-2`.

**미확인**: handcrafted AUC 0.497 / F1 0.438, deep embedding 최고 AUC 0.532.
StudentLife 참가자 수는 자료에 따라 48명 / 49명으로 갈린다 (원 StudentLife
논문은 48명 완료). 인용 시 원문 수치를 따를 것.

## 7. Kim et al. 2026 — 논문 확인, 수치 미확인

*Edge Neuro-Symbolic AI Framework for Privacy-Preserving Real-Time Health
Analytics in Consumer Wearable Devices*, IEEE Transactions on Consumer
Electronics (2026). IEEE Xplore 문서번호 11305223.

초록으로 확인: federated learning + 동형암호 + symbolic reasoning,
ECG / PPG / 가속도 다중모달, 자원 제약 웨어러블 대상.
**미확인**: anomaly detection accuracy 94.8%, 암호화 지연 약 35 ms.
공개 full text 가 없으므로 학교 IEEE 구독으로 확보할 것.

## 8. Norman et al. 2026 — 확인

*Wearable ANS monitoring in real life: A critical review of context-sensitive
interpretation and implications for psychophysiology*, Autonomic Neuroscience
(2026). ScienceDirect PII `S1566070225001262`.

제목이 계획 문서와 정확히 일치한다. 정성적 주장(생리신호는 맥락 의존적이며
단독 해석하면 안 된다)이 우리 연구동기의 근거이므로 정량 수치는 필요 없다.

---

## 데이터셋 접근 조건

| 데이터 | 접근 | 규모 | 비고 |
| --- | --- | --- | --- |
| Stress & Exercise (PhysioNet) | Open | 69.7 MB zip / 247.4 MB | 지금 바로 |
| WESAD (UCI) | Open | 15명 | 지금 바로 |
| ScientISST MOVE (PhysioNet) | Open | 17명 | 지금 바로 |
| **CovIdentify (PhysioNet)** | **Credentialed** | 2,887명 | **지금 신청할 것** |
| UCI HAR | Open | 30명 | 보조 |
| StudentLife | Open | 48명 | 보조 |

CovIdentify 는 PhysioNet credentialed 계정 + CITI 교육 이수 + DUA 서명이
필요하고 승인까지 수 주가 걸린다. Phase 8 은 2주 계획 밖이지만 **신청은
다른 작업과 무관하게 지금 넣어야** 나중에 병목이 되지 않는다.
