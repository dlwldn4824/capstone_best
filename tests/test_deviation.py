"""설명 상한 — 설명이 붙었다고 이탈이 사라지지는 않는다."""
import numpy as np
import pandas as pd

from src.nesy import deviation as dv


def test_explanation_ceiling_keeps_extreme_windows_open():
    """설명이 붙어도 그 설명이 감당할 크기를 넘으면 닫히지 않아야 한다.

    운동한 날에도 아플 수 있다. 설명을 이유로 창을 닫아버리면
    자기보고가 곧 무죄 증명이 되어버린다.
    """
    dev = np.array([0.1, 1.0, 1.1, 1.2, 6.0])
    ev = {
        "EXERCISE_EVIDENCE": pd.Series([0.0, 1.0, 1.0, 1.0, 1.0]),
        "STRESS_EVIDENCE": pd.Series([0.0, 0.0, 0.0, 0.0, 0.0]),
    }
    plain = dv.explain(dev, ev, dev_thresh=0.5)
    assert plain[4] == dv.EXPLAINED_EXERCISE          # 상한이 없으면 닫힌다
    assert dv.carried_forward(plain).sum() == 0

    capped = dv.explain(dev, ev, dev_thresh=0.5,
                        ceiling={dv.EXPLAINED_EXERCISE: 1.5})
    assert capped[4] == dv.EXCEEDS_EXPLANATION        # 상한을 두면 남는다
    assert list(capped[1:4]) == [dv.EXPLAINED_EXERCISE] * 3   # 보통 크기는 그대로 닫힘
    assert dv.carried_forward(capped).sum() == 1


def test_cause_ceiling_is_fit_on_train_only():
    """상한도 임계값과 같다. test fold 를 보고 정하면 누수다."""
    rng = np.random.default_rng(0)
    dev = np.concatenate([rng.normal(1.0, 0.2, 60), rng.normal(9.0, 0.2, 60)])
    tags = np.array([dv.EXPLAINED_EXERCISE] * 120, dtype=object)
    train = np.zeros(120, dtype=bool)
    train[:60] = True                                  # 앞 60개만 학습

    cap = dv.fit_cause_ceiling(dev, tags, train_mask=train)[dv.EXPLAINED_EXERCISE]
    assert cap is not None and cap < 2.0                # 뒤쪽 9.0 을 못 봤어야 한다

    dev2 = dev.copy()
    dev2[60:] = 999.0                                   # test fold 를 오염시켜도
    cap2 = dv.fit_cause_ceiling(dev2, tags, train_mask=train)[dv.EXPLAINED_EXERCISE]
    assert cap2 == cap                                  # 상한은 변하지 않아야 한다


def test_cause_ceiling_abstains_when_too_few_samples():
    """근거가 부족하면 상한을 두지 않는다 — 함부로 자르면 오탐이 는다."""
    dev = np.arange(10, dtype=float)
    tags = np.array([dv.EXPLAINED_STRESS] * 10, dtype=object)
    assert dv.fit_cause_ceiling(dev, tags)[dv.EXPLAINED_STRESS] is None
