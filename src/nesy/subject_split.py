"""Subject-independent split.

원 논문은 80/20 + 10-fold CV 를 쓰지만 같은 피험자의 윈도가 train/test 양쪽에
들어갈 수 있다. 60초 윈도를 30초 간격으로 겹쳐 뽑으면 인접 윈도가 거의 동일한
신호를 공유하므로, 이 누수는 성능을 크게 부풀린다. 우리는 subject 단위 분할을
기본으로 쓰고 random split 은 '누수가 얼마나 부풀리는지'를 보여주는
대조군으로만 보고한다.

담당: 역할 B (모델/평가)
"""
from __future__ import annotations

import numpy as np
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut, StratifiedKFold


def make_splits(df, scheme="group_kfold", n_splits=5, label_col="label",
                group_col="subject_id", random_state=42):
    """(train_idx, test_idx, fold_name) 의 리스트를 돌려준다.

    scheme
      group_kfold : subject 를 그룹으로 하는 K-fold   (기본)
      loso        : Leave-One-Subject-Out
      random      : StratifiedKFold, subject 무시     (대조군, 누수 있음)
    """
    y = df[label_col].to_numpy()
    groups = df[group_col].to_numpy()

    if scheme == "loso":
        splitter = LeaveOneGroupOut()
        for tr, te in splitter.split(df, y, groups):
            yield tr, te, str(groups[te][0])
        return

    if scheme == "random":
        splitter = StratifiedKFold(n_splits=n_splits, shuffle=True,
                                   random_state=random_state)
        for i, (tr, te) in enumerate(splitter.split(df, y)):
            yield tr, te, "fold{}".format(i)
        return

    if scheme == "group_kfold":
        n = min(n_splits, len(np.unique(groups)))
        splitter = GroupKFold(n_splits=n)
        for i, (tr, te) in enumerate(splitter.split(df, y, groups)):
            yield tr, te, "fold{}".format(i)
        return

    raise ValueError("알 수 없는 split scheme: {}".format(scheme))


def split_summary(df, scheme, n_splits=5, **kw):
    """분할이 정상인지(테스트 폴드에 클래스가 다 있는지) 확인용."""
    rows = []
    for tr, te, name in make_splits(df, scheme, n_splits, **kw):
        rows.append({
            "fold": name,
            "n_train": len(tr), "n_test": len(te),
            "train_subjects": df.iloc[tr]["subject_id"].nunique(),
            "test_subjects": df.iloc[te]["subject_id"].nunique(),
            "test_classes": df.iloc[te]["label"].nunique(),
            "leak": bool(set(df.iloc[tr]["subject_id"])
                         & set(df.iloc[te]["subject_id"])),
        })
    return rows
