# 개인 baseline 이탈 + 설명 판정


## baseline 선택 방식
| baseline | pooled_auc | mean_subject_auc |
| --- | --- | --- |
| low_activity | 0.648 | 0.619 |
| labeled_rest | 0.77 | 0.789 |
| temporal | 0.477 | 0.462 |

## 설명 판정 x 실제 상태
| label | EXPLAINED_EXERCISE | EXPLAINED_STRESS | NOT_DEVIATING | UNEXPLAINED |
| --- | --- | --- | --- | --- |
| EXERCISE | 61 | 4 | 207 | 15 |
| REST | 9 | 5 | 412 | 140 |
| STRESS | 13 | 25 | 163 | 197 |

## Exp 1c 맥락 은닉 (운동 규칙 제거)
운동 구간 287개 중 이탈로 잡힌 80개에 대해

- 우리 구조: `UNEXPLAINED` 95.0%
- 분류기: `STRESS` 로 단정 96.2%

분류기는 기권할 수 없으므로 모르는 맥락을 아는 것 중 하나로 밀어넣는다. 이 차이가 규칙을 두는 이유다.
