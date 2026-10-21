"""Neural baseline: feature MLP (+ 선택적 1D-CNN).

설계 의도 (중요)
    Neural         = HR + HRV + EDA feature 만 사용. ACC(활동 맥락)를 보지 않는다.
    Neural+Context = 위 + ACC feature. 활동 맥락을 '숫자로' 본다.
    NeSy           = Neural 의 출력 + ACC 기반 symbolic evidence.

이렇게 짜야 "activity context 를 숫자로 넣는 것"과 "규칙으로 넣는 것"을
분리해서 비교할 수 있다. ACC 를 이미 넣은 모델과 NeSy 를 비교하면 NeSy 의
이득이 단순히 'ACC 정보 추가' 때문인지 구분할 수 없다.

담당: 역할 B (모델/평가)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from . import evaluate, subject_split


class MLP(nn.Module):
    def __init__(self, n_in, n_out, hidden=(128, 64), p_drop=0.3):
        super().__init__()
        layers, d = [], n_in
        for h in hidden:
            layers += [nn.Linear(d, h), nn.BatchNorm1d(h), nn.ReLU(),
                       nn.Dropout(p_drop)]
            d = h
        self.body = nn.Sequential(*layers)
        self.head = nn.Linear(d, n_out)

    def forward(self, x, return_embedding=False):
        z = self.body(x)
        logits = self.head(z)
        return (logits, z) if return_embedding else logits


class CNN1D(nn.Module):
    """raw BVP/EDA/ACC 윈도용. 시간이 남으면 쓴다 (2주 계획 Day 8 선택 항목)."""

    def __init__(self, n_ch, n_out, width=64):
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv1d(n_ch, width, 7, padding=3), nn.BatchNorm1d(width), nn.ReLU(),
            nn.MaxPool1d(4),
            nn.Conv1d(width, width * 2, 5, padding=2), nn.BatchNorm1d(width * 2), nn.ReLU(),
            nn.MaxPool1d(4),
            nn.Conv1d(width * 2, width * 2, 3, padding=1), nn.BatchNorm1d(width * 2), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1), nn.Flatten())
        self.head = nn.Linear(width * 2, n_out)

    def forward(self, x, return_embedding=False):
        z = self.body(x)
        logits = self.head(z)
        return (logits, z) if return_embedding else logits


def _fit_one(Xtr, ytr, n_classes, seed=42, epochs=120, lr=1e-3, device="cpu"):
    torch.manual_seed(seed)
    model = MLP(Xtr.shape[1], n_classes).to(device)
    # 클래스 불균형 보정 (REST 윈도가 많다)
    counts = np.bincount(ytr, minlength=n_classes).astype(float)
    w = torch.tensor(counts.sum() / np.maximum(counts, 1), dtype=torch.float32,
                     device=device)
    crit = nn.CrossEntropyLoss(weight=w)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    Xt = torch.tensor(Xtr, dtype=torch.float32, device=device)
    yt = torch.tensor(ytr, dtype=torch.long, device=device)
    n, bs = len(Xt), 64
    model.train()
    for _ in range(epochs):
        perm = torch.randperm(n, device=device)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            if len(idx) < 2:      # BatchNorm 은 배치 1을 못 쓴다
                continue
            opt.zero_grad()
            loss = crit(model(Xt[idx]), yt[idx])
            loss.backward()
            opt.step()
        sched.step()
    return model


def run_cv(df, feature_cols, scheme="group_kfold", n_splits=5,
           label_col="label", seed=42, epochs=120, experiment="",
           feature_set="", model_name="mlp", device="cpu"):
    """Neural CV. (metrics, predictions_df(확률 포함), per_fold_df)."""
    classes = sorted(df[label_col].unique())
    cls_idx = {c: i for i, c in enumerate(classes)}
    X_raw = df[feature_cols].to_numpy(dtype=float)
    y = df[label_col].to_numpy()
    y_int = np.asarray([cls_idx[v] for v in y])

    preds = np.empty(len(df), dtype=object)
    confs = np.full(len(df), np.nan)
    proba_all = np.full((len(df), len(classes)), np.nan)
    fold_of = np.empty(len(df), dtype=object)
    per_fold = []

    for tr, te, fold in subject_split.make_splits(
            df, scheme, n_splits, label_col=label_col, random_state=seed):
        # 결측/스케일은 train fold 로만 적합한다 (누수 방지).
        imp = SimpleImputer(strategy="median").fit(X_raw[tr])
        sc = StandardScaler().fit(imp.transform(X_raw[tr]))
        Xtr = sc.transform(imp.transform(X_raw[tr]))
        Xte = sc.transform(imp.transform(X_raw[te]))

        model = _fit_one(Xtr, y_int[tr], len(classes), seed, epochs, device=device)
        model.eval()
        with torch.no_grad():
            logits = model(torch.tensor(Xte, dtype=torch.float32, device=device))
            proba = torch.softmax(logits, dim=1).cpu().numpy()

        p = np.asarray(classes)[np.argmax(proba, axis=1)]
        preds[te] = p
        confs[te] = np.max(proba, axis=1)
        proba_all[te] = proba
        fold_of[te] = fold
        per_fold.append({"fold": fold,
                         **evaluate.compute_metrics(y[te], p, labels=classes)})

    metrics = evaluate.compute_metrics(y, preds, labels=classes)
    pred_df = pd.DataFrame({
        "experiment": experiment, "model": model_name, "split": scheme,
        "feature_set": feature_set, "fold": fold_of,
        "sample_id": df["sample_id"].to_numpy(),
        "subject_id": df["subject_id"].to_numpy(),
        "true_label": y, "pred_label": preds, "confidence": confs,
    })
    # 역할 C 가 쓰는 클래스별 확률 (p_REST / p_STRESS / p_EXERCISE)
    for i, c in enumerate(classes):
        pred_df["p_" + c] = proba_all[:, i]
    return metrics, pred_df, pd.DataFrame(per_fold)
