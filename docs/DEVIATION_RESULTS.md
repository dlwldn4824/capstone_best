# 개인 baseline 이탈 + 설명 판정


## baseline 선택 방식
| baseline | pooled_auc | mean_subject_auc |
| --- | --- | --- |
| low_activity | 0.81 | 0.801 |
| labeled_rest | 0.94 | 0.94 |
| temporal | 0.675 | 0.638 |

## 설명 판정 x 실제 상태
| label | EXPLAINED_EXERCISE | EXPLAINED_STRESS | NOT_DEVIATING | UNEXPLAINED |
| --- | --- | --- | --- | --- |
| EXERCISE | 188 | 3 | 34 | 62 |
| REST | 7 | 5 | 478 | 76 |
| STRESS | 10 | 21 | 214 | 153 |

## Exp 1c 맥락 은닉 (운동 규칙 제거)
운동 구간 287개 중 이탈로 잡힌 253개에 대해

- 우리 구조: `UNEXPLAINED` 98.8%
- 분류기: `STRESS` 로 단정 91.3%

분류기는 기권할 수 없으므로 모르는 맥락을 아는 것 중 하나로 밀어넣는다. 이 차이가 규칙을 두는 이유다.
