#!/usr/bin/env python3
"""
compare_sources.py — Source別学習精度比較スクリプト

backfill完了後に実行して、csv / screen / mixed の3パターンで
モデル精度を比較する。

使い方:
  python compare_sources.py --input-dir /tmp/datasets --output-dir /tmp/compare_results

出力:
  comparison_report.json  — 全パターンの精度メトリクス
  comparison_report.md    — 人間が読めるMarkdownレポート
"""

import argparse
import json
import os
import sys
from datetime import datetime

# ── Import from train.py ──
from train import (
    load_jsonl, extract_features, filter_records_by_source,
    repeated_group_cv, holdout_evaluate,
    MODEL_VERSION, DATE_TAG,
)


def count_source_distribution(records):
    """Count moment_source distribution in records."""
    dist = {"csv": 0, "screen": 0, "both": 0, "none": 0}
    for r in records:
        src = r.get("moment_source", "none")
        dist[src] = dist.get(src, 0) + 1
    return dist


def run_comparison(input_dir, output_dir, targets=None):
    """Run source-filtered training comparison."""
    if targets is None:
        targets = ["click", "order"]

    os.makedirs(output_dir, exist_ok=True)

    # Source filter configurations
    configs = [
        {"name": "mixed (all)", "filter": "all", "description": "全データ（CSV + Screen）で学習"},
        {"name": "csv_only", "filter": "csv_only", "description": "CSV由来の正例のみで学習"},
        {"name": "screen_only", "filter": "screen_only", "description": "Screen由来の正例のみで学習"},
    ]

    # Model configurations
    try:
        import lightgbm as lgb
        has_lgbm = True
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        has_lgbm = False
        from sklearn.linear_model import LogisticRegression

    all_results = {}

    for target in targets:
        input_path = os.path.join(input_dir, f"train_{target}.jsonl")
        if not os.path.exists(input_path):
            print(f"[compare] Skipping {target}: {input_path} not found")
            continue

        print(f"\n{'='*80}")
        print(f"[compare] TARGET: {target}")
        print(f"{'='*80}")

        raw_records = load_jsonl(input_path)
        print(f"[compare] Loaded {len(raw_records)} raw records")

        # Source distribution
        src_dist = count_source_distribution(raw_records)
        print(f"[compare] Source distribution: {json.dumps(src_dist)}")

        target_results = []

        for cfg in configs:
            print(f"\n{'─'*60}")
            print(f"[compare] Config: {cfg['name']} (filter={cfg['filter']})")
            print(f"[compare] {cfg['description']}")

            records = filter_records_by_source(raw_records, cfg["filter"])
            print(f"[compare] Records after filter: {len(records)}")

            if len(records) < 10:
                print(f"[compare] WARNING: Too few records, skipping")
                target_results.append({
                    "config": cfg["name"],
                    "filter": cfg["filter"],
                    "status": "skipped",
                    "reason": "too_few_records",
                    "n_records": len(records),
                })
                continue

            # Extract features
            try:
                X, y, w, group_ids, feature_names, unique_vids, video_ids_raw = \
                    extract_features(records, target=target)
            except Exception as e:
                print(f"[compare] Feature extraction failed: {e}")
                target_results.append({
                    "config": cfg["name"],
                    "filter": cfg["filter"],
                    "status": "error",
                    "error": str(e),
                })
                continue

            n_pos = int(y.sum())
            n_total = len(y)
            n_videos = len(unique_vids)

            print(f"[compare] Samples: {n_total} ({n_pos} positive, {n_pos/max(n_total,1)*100:.1f}%)")
            print(f"[compare] Videos: {n_videos}")

            if n_pos < 3 or (n_total - n_pos) < 3:
                print(f"[compare] WARNING: Insufficient positive/negative samples")
                target_results.append({
                    "config": cfg["name"],
                    "filter": cfg["filter"],
                    "status": "insufficient_data",
                    "n_total": n_total,
                    "n_positive": n_pos,
                    "n_videos": n_videos,
                })
                continue

            # Source distribution after filter
            filtered_src_dist = count_source_distribution(records)

            result = {
                "config": cfg["name"],
                "filter": cfg["filter"],
                "description": cfg["description"],
                "status": "success",
                "n_total": n_total,
                "n_positive": n_pos,
                "n_videos": n_videos,
                "positive_rate": round(n_pos / max(n_total, 1), 4),
                "source_distribution": filtered_src_dist,
                "models": {},
            }

            # ── LR + GroupKFold ──
            n_splits = min(5, n_videos)
            if n_splits < 2:
                n_splits = 2

            lr_params = {
                "class_weight": "balanced",
                "max_iter": 1000,
                "random_state": 42,
                "C": 1.0,
            }

            print(f"  LogisticRegression + GroupKFold ({n_splits}fold x 3repeat)...")
            try:
                lr_agg, lr_folds = repeated_group_cv(
                    X, y, w, group_ids,
                    LogisticRegression, lr_params,
                    n_splits=n_splits, n_repeats=3, use_scaler=True
                )
                result["models"]["lr_group_kfold"] = lr_agg
                print(f"    AUC={lr_agg['auc_mean']:.4f}±{lr_agg['auc_std']:.4f}"
                      f"  P@5={lr_agg['precision_at_5_mean']:.4f}")
            except Exception as e:
                print(f"    Failed: {e}")
                result["models"]["lr_group_kfold"] = {"error": str(e)}

            # ── LR Holdout ──
            try:
                lr_holdout, _ = holdout_evaluate(
                    X, y, w, group_ids, video_ids_raw, unique_vids,
                    LogisticRegression, lr_params, holdout_ratio=0.2, use_scaler=True
                )
                if lr_holdout:
                    result["models"]["lr_holdout"] = lr_holdout
                    print(f"    Holdout AUC={lr_holdout.get('auc', '?')}  P@5={lr_holdout.get('precision_at_5', '?')}")
            except Exception as e:
                print(f"    Holdout failed: {e}")

            # ── LightGBM + GroupKFold ──
            if has_lgbm:
                n_neg = n_total - n_pos
                lgbm_params = {
                    "objective": "binary",
                    "metric": "auc",
                    "verbosity": -1,
                    "n_estimators": 200,
                    "max_depth": 4,
                    "learning_rate": 0.05,
                    "num_leaves": 15,
                    "min_child_samples": max(3, n_pos // 5),
                    "scale_pos_weight": n_neg / max(n_pos, 1),
                    "random_state": 42,
                    "n_jobs": -1,
                }

                print(f"  LightGBM + GroupKFold ({n_splits}fold x 3repeat)...")
                try:
                    lgbm_agg, lgbm_folds = repeated_group_cv(
                        X, y, w, group_ids,
                        lgb.LGBMClassifier, lgbm_params,
                        n_splits=n_splits, n_repeats=3, use_scaler=False
                    )
                    result["models"]["lgbm_group_kfold"] = lgbm_agg
                    print(f"    AUC={lgbm_agg['auc_mean']:.4f}±{lgbm_agg['auc_std']:.4f}"
                          f"  P@5={lgbm_agg['precision_at_5_mean']:.4f}")
                except Exception as e:
                    print(f"    Failed: {e}")
                    result["models"]["lgbm_group_kfold"] = {"error": str(e)}

                # ── LightGBM Holdout ──
                try:
                    lgbm_holdout, _ = holdout_evaluate(
                        X, y, w, group_ids, video_ids_raw, unique_vids,
                        lgb.LGBMClassifier, lgbm_params, holdout_ratio=0.2, use_scaler=False
                    )
                    if lgbm_holdout:
                        result["models"]["lgbm_holdout"] = lgbm_holdout
                        print(f"    Holdout AUC={lgbm_holdout.get('auc', '?')}  P@5={lgbm_holdout.get('precision_at_5', '?')}")
                except Exception as e:
                    print(f"    Holdout failed: {e}")

            target_results.append(result)

        all_results[target] = target_results

    # ═══════════════════════════════════════════════════
    # Generate comparison report
    # ═══════════════════════════════════════════════════
    report = {
        "generated_at": datetime.now().isoformat(),
        "model_version": MODEL_VERSION,
        "date": DATE_TAG,
        "results": all_results,
    }

    # Save JSON
    json_path = os.path.join(output_dir, "comparison_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n[compare] JSON report → {json_path}")

    # Generate Markdown report
    md_lines = [
        f"# Source別学習精度比較レポート",
        f"",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Model Version**: v{MODEL_VERSION}",
        f"",
    ]

    for target, results in all_results.items():
        md_lines.append(f"## Target: {target}")
        md_lines.append("")

        # Comparison table
        md_lines.append("| Config | Samples | Positive | Videos | Pos Rate | LR AUC | LR P@5 | LGBM AUC | LGBM P@5 | Holdout AUC |")
        md_lines.append("|--------|---------|----------|--------|----------|--------|--------|----------|----------|-------------|")

        for r in results:
            if r.get("status") != "success":
                md_lines.append(f"| {r['config']} | — | — | — | — | {r.get('status', '?')} | — | — | — | — |")
                continue

            lr_gk = r["models"].get("lr_group_kfold", {})
            lgbm_gk = r["models"].get("lgbm_group_kfold", {})
            lr_ho = r["models"].get("lr_holdout", {})
            lgbm_ho = r["models"].get("lgbm_holdout", {})

            lr_auc = f"{lr_gk.get('auc_mean', '?')}±{lr_gk.get('auc_std', '?')}" if "error" not in lr_gk else "error"
            lr_p5 = lr_gk.get("precision_at_5_mean", "?") if "error" not in lr_gk else "error"
            lgbm_auc = f"{lgbm_gk.get('auc_mean', '?')}±{lgbm_gk.get('auc_std', '?')}" if lgbm_gk and "error" not in lgbm_gk else "—"
            lgbm_p5 = lgbm_gk.get("precision_at_5_mean", "?") if lgbm_gk and "error" not in lgbm_gk else "—"

            # Best holdout AUC
            best_ho = "—"
            if lgbm_ho and lgbm_ho.get("auc"):
                best_ho = f"{lgbm_ho['auc']}"
            elif lr_ho and lr_ho.get("auc"):
                best_ho = f"{lr_ho['auc']}"

            md_lines.append(
                f"| {r['config']} | {r['n_total']} | {r['n_positive']} | {r['n_videos']} | "
                f"{r['positive_rate']:.1%} | {lr_auc} | {lr_p5} | {lgbm_auc} | {lgbm_p5} | {best_ho} |"
            )

        md_lines.append("")

        # Analysis
        md_lines.append("### 分析")
        md_lines.append("")

        success_results = [r for r in results if r.get("status") == "success"]
        if len(success_results) >= 2:
            # Compare mixed vs csv_only
            mixed = next((r for r in success_results if r["filter"] == "all"), None)
            csv_only = next((r for r in success_results if r["filter"] == "csv_only"), None)
            screen_only = next((r for r in success_results if r["filter"] == "screen_only"), None)

            if mixed and csv_only:
                mixed_auc = mixed["models"].get("lgbm_group_kfold", mixed["models"].get("lr_group_kfold", {})).get("auc_mean", 0) or 0
                csv_auc = csv_only["models"].get("lgbm_group_kfold", csv_only["models"].get("lr_group_kfold", {})).get("auc_mean", 0) or 0
                delta = mixed_auc - csv_auc

                if delta > 0.01:
                    md_lines.append(f"- **Mixed > CSV only**: AUC差 +{delta:.4f} → Screen momentが学習に貢献している")
                elif delta < -0.01:
                    md_lines.append(f"- **CSV only > Mixed**: AUC差 {delta:.4f} → Screen momentがノイズになっている可能性")
                else:
                    md_lines.append(f"- **Mixed ≈ CSV only**: AUC差 {delta:.4f} → Screen momentの影響は軽微")

            if screen_only:
                screen_auc = screen_only["models"].get("lgbm_group_kfold", screen_only["models"].get("lr_group_kfold", {})).get("auc_mean", 0) or 0
                md_lines.append(f"- **Screen only AUC**: {screen_auc:.4f} → Screen単体の教師信号品質")

        md_lines.append("")

    md_path = os.path.join(output_dir, "comparison_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"[compare] Markdown report → {md_path}")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Compare model performance across different moment sources (csv/screen/mixed)"
    )
    parser.add_argument("--input-dir", "-i", required=True,
                        help="Directory containing train_click.jsonl and train_order.jsonl")
    parser.add_argument("--output-dir", "-o", default="/tmp/compare_results/",
                        help="Output directory for comparison reports")
    parser.add_argument("--target", "-t", default=None,
                        choices=["click", "order"],
                        help="Single target to compare (default: both)")
    args = parser.parse_args()

    targets = [args.target] if args.target else ["click", "order"]
    report = run_comparison(args.input_dir, args.output_dir, targets)

    # Print summary
    print(f"\n{'='*80}")
    print("[compare] SUMMARY")
    for target, results in report.get("results", {}).items():
        print(f"\n  [{target}]")
        for r in results:
            if r.get("status") != "success":
                print(f"    {r['config']:20s} → {r.get('status', '?')}")
                continue
            best_model = "lgbm_group_kfold" if "lgbm_group_kfold" in r["models"] and "error" not in r["models"].get("lgbm_group_kfold", {}) else "lr_group_kfold"
            auc = r["models"][best_model].get("auc_mean", "?")
            p5 = r["models"][best_model].get("precision_at_5_mean", "?")
            print(f"    {r['config']:20s} → AUC={auc}  P@5={p5}  (n={r['n_total']}, pos={r['n_positive']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
