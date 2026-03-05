"""
train.py  –  LCJ AI 学習パイプライン v3
========================================
変更点 (v3):
  - GroupKFold(video_id) で動画単位の分割 → リーク防止
  - StratifiedKFold との比較も出力 → 本番耐性チェック
  - モデルレジストリ: manifest.json (version, commit, metrics, feature list)
  - バージョン付きモデルファイル名: model_{target}_{algo}_v{ver}_{date}.pkl

使い方:
  python train.py --input-dir /tmp/datasets --output-dir /tmp/models/
"""

import argparse
import json
import os
import sys
import pickle
import warnings
import hashlib
import subprocess
from datetime import datetime
warnings.filterwarnings("ignore")

import numpy as np

# ── Feature definitions (NO information leak) ──

NUMERIC_FEATURES = [
    "event_duration",
    "event_position_min",
    "event_position_pct",
    "tag_count",
    "cta_score",
    "importance_score",
    "text_length",
    "has_number",
    "exclamation_count",
]

KEYWORD_FEATURES = [
    "kw_price",
    "kw_discount",
    "kw_urgency",
    "kw_cta",
    "kw_quantity",
    "kw_comparison",
    "kw_quality",
    "kw_number",
]

PRODUCT_FEATURES = [
    "product_match",
    "product_match_top3",
    "matched_product_count",
]

KNOWN_EVENT_TYPES = [
    "HOOK", "GREETING", "INTRO", "DEMONSTRATION", "PRICE",
    "CTA", "OBJECTION", "SOCIAL_PROOF", "URGENCY",
    "EMPATHY", "EDUCATION", "CHAT", "TRANSITION", "CLOSING", "UNKNOWN",
]

MODEL_VERSION = 3
DATE_TAG = datetime.now().strftime("%Y%m%d")


def get_git_commit():
    """Get current git commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def load_jsonl(path):
    """Load JSONL file into list of dicts."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def extract_features(records, target="click"):
    """
    Convert records to feature matrix X, label vector y, sample weights w,
    and group IDs (video_id) for GroupKFold.
    """
    y_key = f"y_{target}"

    # Build feature name list
    feature_names = []
    feature_names.extend(NUMERIC_FEATURES)
    feature_names.extend(KEYWORD_FEATURES)
    feature_names.extend(PRODUCT_FEATURES)
    feature_names.extend([f"event_{et}" for et in KNOWN_EVENT_TYPES])

    X = np.zeros((len(records), len(feature_names)), dtype=np.float32)
    y = np.zeros(len(records), dtype=np.int32)
    w = np.ones(len(records), dtype=np.float32)
    groups = []  # video_id for GroupKFold

    for i, rec in enumerate(records):
        col = 0

        # Numeric features
        for feat in NUMERIC_FEATURES:
            val = rec.get(feat)
            X[i, col] = float(val) if val is not None else 0.0
            col += 1

        # Keyword flags
        for feat in KEYWORD_FEATURES:
            X[i, col] = 1.0 if rec.get(feat) else 0.0
            col += 1

        # Product features
        for feat in PRODUCT_FEATURES:
            val = rec.get(feat)
            X[i, col] = float(val) if val is not None else 0.0
            col += 1

        # Event type one-hot
        event_type = rec.get("event_type", "UNKNOWN")
        for et in KNOWN_EVENT_TYPES:
            X[i, col] = 1.0 if event_type == et else 0.0
            col += 1

        # Label
        y[i] = int(rec.get(y_key, 0))

        # Sample weight
        sample_w = rec.get("sample_weight", 1.0)
        w[i] = float(sample_w) if sample_w and sample_w > 0 else 1.0

        # Group ID (video_id → integer hash for GroupKFold)
        groups.append(rec.get("video_id", f"unknown_{i}"))

    # Convert video_id strings to integer group IDs
    unique_vids = sorted(set(groups))
    vid_to_gid = {v: i for i, v in enumerate(unique_vids)}
    group_ids = np.array([vid_to_gid[g] for g in groups], dtype=np.int32)

    return X, y, w, group_ids, feature_names, unique_vids


def precision_at_k(y_true, y_scores, k=5):
    """Compute Precision@K."""
    if len(y_true) <= k:
        k = len(y_true)
    top_k_idx = np.argsort(y_scores)[::-1][:k]
    return float(np.sum(y_true[top_k_idx])) / k


def evaluate_cv(X, y, w, groups, model_class, model_params, cv_strategy, feature_names,
                use_scaler=False, use_sample_weight=True):
    """
    Run cross-validation and return metrics dict.

    Args:
        cv_strategy: a CV splitter (GroupKFold or StratifiedKFold)
        use_scaler: whether to apply StandardScaler
    """
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score, precision_score, recall_score, f1_score

    y_pred = np.zeros(len(y), dtype=np.float64)
    split_args = (X, y) if groups is None else (X, y, groups)

    for train_idx, val_idx in cv_strategy.split(*split_args):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, w_tr = y[train_idx], w[train_idx]

        if use_scaler:
            scaler = StandardScaler()
            X_tr = scaler.fit_transform(X_tr)
            X_val = scaler.transform(X_val)

        model = model_class(**model_params)
        if use_sample_weight:
            try:
                model.fit(X_tr, y_tr, sample_weight=w_tr)
            except TypeError:
                model.fit(X_tr, y_tr)
        else:
            model.fit(X_tr, y_tr)

        y_pred[val_idx] = model.predict_proba(X_val)[:, 1]

    # Compute metrics
    try:
        auc = roc_auc_score(y, y_pred)
    except ValueError:
        auc = 0.0

    y_binary = (y_pred >= 0.5).astype(int)
    prec = precision_score(y, y_binary, zero_division=0)
    rec = recall_score(y, y_binary, zero_division=0)
    f1 = f1_score(y, y_binary, zero_division=0)
    p_at_5 = precision_at_k(y, y_pred, k=5)

    return {
        "auc": round(auc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "precision_at_5": round(p_at_5, 4),
    }


def train_and_evaluate(X, y, w, group_ids, feature_names, unique_vids, target, output_dir):
    """Train models with both GroupKFold and StratifiedKFold, compare results."""
    from sklearn.model_selection import GroupKFold, StratifiedKFold
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    try:
        import lightgbm as lgb
        has_lgbm = True
    except ImportError:
        print("[train] LightGBM not installed. Using only LogisticRegression.")
        has_lgbm = False

    os.makedirs(output_dir, exist_ok=True)
    metrics = {"target": target, "model_version": MODEL_VERSION}

    n_positive = int(y.sum())
    n_total = len(y)
    n_videos = len(unique_vids)

    print(f"\n[train] Target: {target}")
    print(f"[train] Dataset: {n_total} samples, {n_positive} positive ({n_positive/max(n_total,1)*100:.1f}%)")
    print(f"[train] Videos: {n_videos} unique")

    if n_positive < 3 or (n_total - n_positive) < 3:
        print("[train] WARNING: Too few samples for meaningful training.")
        metrics["status"] = "insufficient_data"
        metrics["n_total"] = n_total
        metrics["n_positive"] = n_positive
        with open(os.path.join(output_dir, f"eval_metrics_{target}.json"), "w") as f:
            json.dump(metrics, f, indent=2)
        return metrics

    # ── CV strategies ──
    # GroupKFold: same video never in both train and test
    n_group_splits = min(5, n_videos)
    if n_group_splits < 2:
        n_group_splits = 2
    group_cv = GroupKFold(n_splits=n_group_splits)

    # StratifiedKFold: for comparison (may leak across videos)
    n_strat_splits = min(5, n_positive, n_total - n_positive)
    if n_strat_splits < 2:
        n_strat_splits = 2
    strat_cv = StratifiedKFold(n_splits=n_strat_splits, shuffle=True, random_state=42)

    # ── Model configs ──
    lr_params = {
        "class_weight": "balanced",
        "max_iter": 1000,
        "random_state": 42,
        "C": 1.0,
    }

    n_neg = n_total - n_positive
    lgbm_params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        "n_estimators": 200,
        "max_depth": 4,
        "learning_rate": 0.05,
        "num_leaves": 15,
        "min_child_samples": max(3, n_positive // 5),
        "scale_pos_weight": n_neg / max(n_positive, 1),
        "random_state": 42,
        "n_jobs": -1,
    }

    # ── Evaluate all combinations ──
    print(f"\n[train] === GroupKFold ({n_group_splits} folds, {n_videos} videos) ===")

    # LR + GroupKFold
    print(f"  LogisticRegression + GroupKFold...")
    try:
        m_lr_group = evaluate_cv(
            X, y, w, group_ids, LogisticRegression, lr_params,
            group_cv, feature_names, use_scaler=True
        )
        print(f"    AUC={m_lr_group['auc']:.4f}  P@5={m_lr_group['precision_at_5']:.4f}  F1={m_lr_group['f1']:.4f}")
    except Exception as e:
        print(f"    Failed: {e}")
        m_lr_group = {"error": str(e)}

    # LightGBM + GroupKFold
    m_lgbm_group = None
    if has_lgbm:
        print(f"  LightGBM + GroupKFold...")
        try:
            m_lgbm_group = evaluate_cv(
                X, y, w, group_ids, lgb.LGBMClassifier, lgbm_params,
                group_cv, feature_names, use_scaler=False
            )
            print(f"    AUC={m_lgbm_group['auc']:.4f}  P@5={m_lgbm_group['precision_at_5']:.4f}  F1={m_lgbm_group['f1']:.4f}")
        except Exception as e:
            print(f"    Failed: {e}")
            m_lgbm_group = {"error": str(e)}

    print(f"\n[train] === StratifiedKFold ({n_strat_splits} folds, reference) ===")

    # LR + StratifiedKFold (reference)
    print(f"  LogisticRegression + StratifiedKFold...")
    try:
        m_lr_strat = evaluate_cv(
            X, y, w, None, LogisticRegression, lr_params,
            strat_cv, feature_names, use_scaler=True
        )
        print(f"    AUC={m_lr_strat['auc']:.4f}  P@5={m_lr_strat['precision_at_5']:.4f}  F1={m_lr_strat['f1']:.4f}")
    except Exception as e:
        print(f"    Failed: {e}")
        m_lr_strat = {"error": str(e)}

    # LightGBM + StratifiedKFold (reference)
    m_lgbm_strat = None
    if has_lgbm:
        print(f"  LightGBM + StratifiedKFold...")
        try:
            m_lgbm_strat = evaluate_cv(
                X, y, w, None, lgb.LGBMClassifier, lgbm_params,
                strat_cv, feature_names, use_scaler=False
            )
            print(f"    AUC={m_lgbm_strat['auc']:.4f}  P@5={m_lgbm_strat['precision_at_5']:.4f}  F1={m_lgbm_strat['f1']:.4f}")
        except Exception as e:
            print(f"    Failed: {e}")
            m_lgbm_strat = {"error": str(e)}

    # ── Store all evaluation results ──
    metrics["evaluation"] = {
        "group_kfold": {
            "n_splits": n_group_splits,
            "n_videos": n_videos,
            "lr": m_lr_group,
        },
        "stratified_kfold": {
            "n_splits": n_strat_splits,
            "lr": m_lr_strat,
        },
    }
    if m_lgbm_group is not None:
        metrics["evaluation"]["group_kfold"]["lgbm"] = m_lgbm_group
    if m_lgbm_strat is not None:
        metrics["evaluation"]["stratified_kfold"]["lgbm"] = m_lgbm_strat

    # ── Comparison summary ──
    print(f"\n[train] === COMPARISON ===")
    print(f"  {'Model':<20} {'GroupKFold AUC':>15} {'StratKFold AUC':>15} {'Delta':>10}")
    print(f"  {'-'*60}")
    for algo in ["lr", "lgbm"]:
        g = metrics["evaluation"]["group_kfold"].get(algo, {})
        s = metrics["evaluation"]["stratified_kfold"].get(algo, {})
        g_auc = g.get("auc", 0)
        s_auc = s.get("auc", 0)
        delta = s_auc - g_auc
        label = "LogReg" if algo == "lr" else "LightGBM"
        if g_auc > 0 and s_auc > 0:
            print(f"  {label:<20} {g_auc:>15.4f} {s_auc:>15.4f} {delta:>+10.4f}")
            if delta > 0.05:
                print(f"  ⚠️  {label}: StratifiedKFold is {delta:.4f} higher → possible video-level leak")
            else:
                print(f"  ✅  {label}: GroupKFold holds up well (delta < 0.05)")

    # ── Train final models on all data ──
    print(f"\n[train] Training final models on all data...")

    # Final LR
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    lr_final = LogisticRegression(**lr_params)
    lr_final.fit(X_scaled, y, sample_weight=w)

    lr_filename = f"model_{target}_lr_v{MODEL_VERSION}_{DATE_TAG}.pkl"
    with open(os.path.join(output_dir, lr_filename), "wb") as f:
        pickle.dump({"model": lr_final, "scaler": scaler, "target": target,
                      "version": MODEL_VERSION, "date": DATE_TAG}, f)
    # Also save as latest (for API compatibility)
    with open(os.path.join(output_dir, f"model_{target}_lr.pkl"), "wb") as f:
        pickle.dump({"model": lr_final, "scaler": scaler, "target": target,
                      "version": MODEL_VERSION, "date": DATE_TAG}, f)
    print(f"  Saved: {lr_filename}")

    # Final LightGBM
    lgbm_filename = None
    feat_imp_list = []
    if has_lgbm:
        lgbm_final = lgb.LGBMClassifier(**lgbm_params)
        lgbm_final.fit(X, y, sample_weight=w)

        lgbm_filename = f"model_{target}_lgbm_v{MODEL_VERSION}_{DATE_TAG}.pkl"
        with open(os.path.join(output_dir, lgbm_filename), "wb") as f:
            pickle.dump({"model": lgbm_final, "target": target,
                          "version": MODEL_VERSION, "date": DATE_TAG}, f)
        with open(os.path.join(output_dir, f"model_{target}_lgbm.pkl"), "wb") as f:
            pickle.dump({"model": lgbm_final, "target": target,
                          "version": MODEL_VERSION, "date": DATE_TAG}, f)
        print(f"  Saved: {lgbm_filename}")

        # Feature importance
        importances = lgbm_final.feature_importances_
        feat_imp_list = sorted(
            zip(feature_names, importances.tolist()),
            key=lambda x: x[1], reverse=True
        )
        print("\n  Top 10 features:")
        for fname, imp in feat_imp_list[:10]:
            print(f"    {fname:30s} {imp:6.0f}")

    # ── Determine best model (based on GroupKFold) ──
    best_model = "lr"
    best_auc = m_lr_group.get("auc", 0) if isinstance(m_lr_group, dict) else 0
    if m_lgbm_group and isinstance(m_lgbm_group, dict):
        lgbm_auc = m_lgbm_group.get("auc", 0)
        if lgbm_auc > best_auc:
            best_model = "lgbm"
            best_auc = lgbm_auc

    metrics["best_model"] = best_model
    metrics["best_auc_group_kfold"] = best_auc
    metrics["status"] = "success"
    metrics["n_total"] = n_total
    metrics["n_positive"] = n_positive
    metrics["n_videos"] = n_videos
    metrics["positive_rate"] = round(n_positive / max(n_total, 1), 4)
    metrics["n_features"] = len(feature_names)
    if feat_imp_list:
        metrics["feature_importance"] = [
            {"feature": fn, "importance": imp} for fn, imp in feat_imp_list[:20]
        ]

    # Save metrics
    with open(os.path.join(output_dir, f"eval_metrics_{target}.json"), "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)

    # Save feature names
    with open(os.path.join(output_dir, "feature_names.json"), "w") as f:
        json.dump(feature_names, f, indent=2)

    print(f"\n[train] Best model for {target}: {best_model} (GroupKFold AUC={best_auc:.4f})")
    return metrics, lr_filename, lgbm_filename


def build_manifest(all_metrics, output_dir, feature_names):
    """Build manifest.json for model registry."""
    commit = get_git_commit()

    manifest = {
        "model_version": MODEL_VERSION,
        "date": DATE_TAG,
        "commit": commit,
        "trained_at": datetime.now().isoformat(),
        "feature_names": feature_names,
        "n_features": len(feature_names),
        "models": {},
    }

    for target, (metrics, lr_file, lgbm_file) in all_metrics.items():
        manifest["models"][target] = {
            "best_model": metrics.get("best_model", "lr"),
            "best_auc_group_kfold": metrics.get("best_auc_group_kfold", 0),
            "n_total": metrics.get("n_total", 0),
            "n_positive": metrics.get("n_positive", 0),
            "n_videos": metrics.get("n_videos", 0),
            "files": {
                "lr": lr_file,
                "lgbm": lgbm_file,
            },
            "evaluation": metrics.get("evaluation", {}),
        }

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\n[train] Manifest → {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Train LCJ AI prediction model v3")
    parser.add_argument("--input", "-i", default=None,
                        help="Input JSONL dataset file (single target)")
    parser.add_argument("--input-dir", default=None,
                        help="Input directory containing train_click.jsonl and train_order.jsonl")
    parser.add_argument("--target", "-t", default="click",
                        choices=["click", "order"],
                        help="Target label (click or order)")
    parser.add_argument("--output-dir", "-o", default="/tmp/models/",
                        help="Output directory for models and metrics")
    args = parser.parse_args()

    all_results = {}
    feature_names_final = None

    if args.input_dir:
        for target in ["click", "order"]:
            input_path = os.path.join(args.input_dir, f"train_{target}.jsonl")
            if not os.path.exists(input_path):
                print(f"[train] Skipping {target}: {input_path} not found")
                continue

            print(f"\n{'='*60}")
            print(f"[train] Loading {target} dataset from: {input_path}")
            records = load_jsonl(input_path)
            print(f"[train] Loaded {len(records)} records")

            X, y, w, group_ids, feature_names, unique_vids = extract_features(records, target=target)
            feature_names_final = feature_names
            print(f"[train] Feature matrix: {X.shape}, {len(unique_vids)} videos")

            metrics, lr_file, lgbm_file = train_and_evaluate(
                X, y, w, group_ids, feature_names, unique_vids, target, args.output_dir
            )
            all_results[target] = (metrics, lr_file, lgbm_file)

    elif args.input:
        if not os.path.exists(args.input):
            print(f"[train] ERROR: Input file not found: {args.input}")
            sys.exit(1)

        records = load_jsonl(args.input)
        X, y, w, group_ids, feature_names, unique_vids = extract_features(records, target=args.target)
        feature_names_final = feature_names

        metrics, lr_file, lgbm_file = train_and_evaluate(
            X, y, w, group_ids, feature_names, unique_vids, args.target, args.output_dir
        )
        all_results[args.target] = (metrics, lr_file, lgbm_file)

    else:
        print("[train] ERROR: Specify --input or --input-dir")
        sys.exit(1)

    # Build manifest
    if feature_names_final and all_results:
        manifest = build_manifest(all_results, args.output_dir, feature_names_final)

    # Summary
    print(f"\n{'='*60}")
    print("[train] FINAL SUMMARY")
    print(f"  Model Version: v{MODEL_VERSION} ({DATE_TAG})")
    print(f"  Commit: {get_git_commit()}")
    for target, (m, _, _) in all_results.items():
        best = m.get("best_model", "?")
        auc_g = m.get("best_auc_group_kfold", 0)
        g_eval = m.get("evaluation", {}).get("group_kfold", {})
        s_eval = m.get("evaluation", {}).get("stratified_kfold", {})
        g_p5 = g_eval.get(best, {}).get("precision_at_5", "?")
        s_auc = s_eval.get(best, {}).get("auc", 0)
        delta = s_auc - auc_g if isinstance(s_auc, float) and isinstance(auc_g, float) else "?"
        print(f"\n  [{target}]")
        print(f"    Best: {best}")
        print(f"    GroupKFold AUC:     {auc_g:.4f}")
        print(f"    StratifiedKFold AUC: {s_auc:.4f}" if isinstance(s_auc, float) else f"    StratifiedKFold AUC: {s_auc}")
        print(f"    Delta:              {delta:+.4f}" if isinstance(delta, float) else f"    Delta:              {delta}")
        print(f"    Precision@5 (Group): {g_p5}")

    print(f"\n[train] All outputs saved to: {args.output_dir}")

    success = all(m.get("status") == "success" for m, _, _ in all_results.values())
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
