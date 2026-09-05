"""Logistic Regression / Random Forest / XGBoost baseline.

원 논문(Hongn 2025) 재현과 우리 subject-independent 재평가를 같은 코드로 돈다.

담당: 역할 B (모델/평가)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from . import evaluate, subject_split


def make_model(name, seed=42, n_classes=3):
    """이름 -> sklearn 호환 파이프라인."""
    if name == "logreg":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced",
                                       random_state=seed)),
        ])
    if name == "rf":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median")),
            ("clf", RandomForestClassifier(n_estimators=400, n_jobs=-1,
                                           class_weight="balanced_subsample",
                                           random_state=seed)),
        ])
    if name == "xgboost":
        from xgboost import XGBClassifier
        # XGBoost 는 NaN 을 직접 처리하므로 imputer 를 넣지 않는다.
        return XGBClassifier(
            n_estimators=400, max_depth=5, learning_rate=0.08,
            subsample=0.9, colsample_bytree=0.9, reg_lambda=1.0,
            objective="multi:softprob" if n_classes > 2 else "binary:logistic",
            num_class=n_classes if n_classes > 2 else None,
            tree_method="hist", random_state=seed, n_jobs=-1,
            eval_metric="mlogloss" if n_classes > 2 else "logloss")
    raise ValueError("알 수 없는 모델: {}".format(name))


def _encode(y, classes):
    idx = {c: i for i, c in enumerate(classes)}
    return np.asarray([idx[v] for v in y])


def run_cv(df, feature_cols, model_name, scheme="group_kfold", n_splits=5,
           label_col="label", seed=42, experiment="", feature_set=""):
    """교차검증 1회 실행 -> (metrics, predictions_df, per_fold_df).

    fold 별로 모델을 새로 학습하며, XGBoost 는 라벨을 정수로 인코딩한다.
    """
    classes = sorted(df[label_col].unique())
    X = df[feature_cols].to_numpy(dtype=float)
    y = df[label_col].to_numpy()

    preds = np.empty(len(df), dtype=object)
    confs = np.full(len(df), np.nan)
    fold_of = np.empty(len(df), dtype=object)

    per_fold = []
    for tr, te, fold in subject_split.make_splits(
            df, scheme, n_splits, label_col=label_col, random_state=seed):
        model = make_model(model_name, seed, n_classes=len(classes))
        if model_name == "xgboost":
            model.fit(X[tr], _encode(y[tr], classes))
            proba = model.predict_proba(X[te])
            p = np.asarray(classes)[np.argmax(proba, axis=1)]
        else:
            model.fit(X[tr], y[tr])
            proba = model.predict_proba(X[te])
            p = model.classes_[np.argmax(proba, axis=1)]

        preds[te] = p
        confs[te] = np.max(proba, axis=1)
        fold_of[te] = fold
        per_fold.append({"fold": fold, **evaluate.compute_metrics(
            y[te], p, labels=classes)})

    metrics = evaluate.compute_metrics(y, preds, labels=classes)
    pred_df = pd.DataFrame({
        "experiment": experiment, "model": model_name, "split": scheme,
        "feature_set": feature_set, "fold": fold_of,
        "sample_id": df["sample_id"].to_numpy(),
        "subject_id": df["subject_id"].to_numpy(),
        "true_label": y, "pred_label": preds, "confidence": confs,
    })
    return metrics, pred_df, pd.DataFrame(per_fold)


def feature_importance(df, feature_cols, model_name="xgboost",
                       label_col="label", seed=42, top=25):
    """전체 데이터로 한 번 학습해 feature importance 를 뽑는다 (해석 전용)."""
    classes = sorted(df[label_col].unique())
    X = df[feature_cols].to_numpy(dtype=float)
    y = df[label_col].to_numpy()
    model = make_model(model_name, seed, n_classes=len(classes))
    if model_name == "xgboost":
        model.fit(X, _encode(y, classes))
        imp = model.feature_importances_
    else:
        model.fit(X, y)
        step = model[-1] if isinstance(model, Pipeline) else model
        imp = getattr(step, "feature_importances_", None)
        if imp is None:
            imp = np.abs(step.coef_).mean(axis=0)
    return (pd.DataFrame({"feature": feature_cols, "importance": imp})
            .sort_values("importance", ascending=False)
            .head(top).reset_index(drop=True))
