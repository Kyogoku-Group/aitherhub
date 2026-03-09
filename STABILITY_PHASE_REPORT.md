# Worker Stability Phase 完了報告書

## 目的

前回のWorker/API分離リファクタリングを基盤とし、動画処理システムとして本番運用レベルの安定性を実現するため、以下の5つの機能を追加・強化しました。

1.  **Worker Crash Recovery**: Workerがクラッシュしてもジョブが永久停止しない仕組み
2.  **Temp File Management**: ディスク溢れを防止する一時ファイル管理
3.  **Worker Health Monitoring**: Workerの状態を外部から監視する機能の強化
4.  **Worker Metrics Logging**: パフォーマンスボトルネックを特定するための指標ログ
5.  **Worker Startup Self Check**: 起動時に依存関係を検証し、異常があれば即時停止する仕組み

これにより、AitherHubの動画処理パイプラインは、完全自動で安定稼働するシステムへと進化しました。

---

## 実装内容サマリー

### Task 1: Worker Crash Recovery (ジョブ停止防止)

**実装概要:**
-   **Heartbeat Manager**: 稼働中のジョブIDを管理し、30秒ごとにDBの`heartbeat_at`を更新するバックグラウンドスレッドを実装しました。
-   **Stalled Job Recovery**: 2分以上heartbeatが途絶えたジョブを「stalled」とみなし、自動で検知・回復処理を行うバックグラウンドスレッドを実装しました。
-   **Retry/Deadロジック**: Stalledジョブは`attempt_count`をインクリメントして再キューイングされます。試行回数が上限（`MAX_ATTEMPTS=3`）に達したジョブは`status='dead'`となり、永久に停止します。

**成果物:**
-   `worker/recovery/heartbeat_manager.py`
-   `worker/recovery/stalled_job_recovery.py`
-   `worker/entrypoints/queue_worker.py` への統合コード

### Task 2: Temp File Management (ディスク溢れ防止)

**実装概要:**
-   **ジョブごとの独立ディレクトリ**: 各ジョブ（clip/video）は `/tmp/aitherhub/{job_id}/` という独立した一時ディレクトリ内で処理されるようになりました。
-   **自動クリーンアップ**: `with`構文（コンテキストマネージャ）を導入し、ジョブの成功・失敗に関わらず、処理終了後に`finally`ブロックで一時ディレクトリが確実に削除される構造に変更しました。
-   **起動時クリーンアップ**: Worker起動時に、前回のクラッシュ等で残存した6時間以上前の一時ディレクトリを自動で全削除する処理を追加しました。

**成果物:**
-   `worker/recovery/temp_manager.py`
-   `worker/entrypoints/queue_worker.py` の `_run_clip_job`, `_run_video_job` への統合コード

### Task 3: Worker Health Monitoring (監視強化)

**実装概要:**
-   **Storage Access Check**: 既存のHealth Checkエンドポイント (`/worker/health`) に、Azure Blob Storageへの接続性を確認するチェックを追加しました。
-   **Disk Space閾値変更**: ディスク空き容量の警告閾値を、指示書通り5GBに変更しました (`free_space < 5GB` で `warning`)。

**成果物:**
-   `worker/entrypoints/health_check.py` (修正)

### Task 4: Worker Metrics Logging (パフォーマンス計測)

**実装概要:**
-   **Metrics Logger**: ジョブの各フェーズ（download, encode, upload等）の処理時間や、動画サイズ、クリップ長などのパフォーマンス指標を計測・記録する専用モジュールを実装しました。
-   **構造化ログ**: 全ての指標は `worker.metrics.clip_processing` というキーを持つJSON形式の構造化ログとして出力され、分析が容易になりました。

**成果物:**
-   `worker/recovery/metrics_logger.py`
-   `worker/entrypoints/queue_worker.py` への統合コード

### Task 5: Worker Startup Self Check (起動時検証)

**実装概要:**
-   **起動前検証**: Workerがキューのポーリングを開始する前に、FFmpeg, DB接続, Queue接続, 一時ディレクトリ書き込み権限など、全ての必須依存関係を検証する処理を実装しました。
-   **即時Exit**: いずれかのチェックに失敗した場合、Workerはエラーログを出力して即座に異常終了します。これにより、壊れたWorkerがリソースを消費し続ける事態を防ぎます。

**成果物:**
-   `worker/recovery/startup_check.py`
-   `worker/entrypoints/queue_worker.py` の `main()` 関数への統合コード

---

## 成果物一覧

### 1. 新規作成された主要ロジック

-   `worker/recovery/heartbeat_manager.py`: ジョブの生存確認（ハートビート）を管理します。
-   `worker/recovery/stalled_job_recovery.py`: 停止したジョブを自動で検知し、再実行または停止させます。
-   `worker/recovery/temp_manager.py`: 一時ファイルをジョブごとに隔離し、自動でクリーンアップします。
-   `worker/recovery/metrics_logger.py`: ジョブのパフォーマンスを計測し、構造化ログとして出力します。
-   `worker/recovery/startup_check.py`: Worker起動時に、全ての依存関係が正常であるかを確認します。

### 2. 修正・統合された主要ファイル

-   `worker/entrypoints/queue_worker.py`: 上記の安定化モジュール群を統合した、新しいWorkerのメインエントリーポイントです。
-   `worker/entrypoints/health_check.py`: Health Check項目にAzure Storageへの接続確認を追加しました。

### 3. データベースマイグレーション

-   `backend/migrations/add_clip_jobs_v1.sql`: （前回作成済みですが）Crash Recoveryの基盤となるDBカラム（`heartbeat_at`, `attempt_count`等）を追加するSQLです。

全てのコードは、CIルールである「`worker/`から`app/`をimport禁止」を遵守しています。
