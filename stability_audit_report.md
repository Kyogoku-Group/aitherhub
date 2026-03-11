# コードベース安定性監査レポート

## 1. はじめに

本レポートは、`aitherhub-lcj` プロジェクトの既存機能を保護し、システム全体の安定性を向上させることを目的としたコードベース監査の結果をまとめたものです。監査では、潜在的なバグ、レースコンディション、エラーハンドリングの欠陥、技術的負債を特定し、それらを解消するための具体的なリファクタリング計画を提案します。

## 2. 監査結果サマリー

監査の結果、データベース管理、APIの堅牢性、非同期タスク処理、コード品質など、複数の領域にわたって重要な問題が発見されました。これらの問題は、システムの信頼性、パフォーマンス、保守性に深刻な影響を与える可能性があります。以下に、特定された主要な問題とその優先度を示します。

| 優先度 | 問題カテゴリ | 概要 |
| :--- | :--- | :--- |
| **Critical** | データベース | SQL方言の混在、不適切なトランザクション管理、N+1クエリ |
| **Critical** | バックエンドAPI | 不十分なエラーハンドリング、巨大すぎる関数 |
| **High** | Workerプロセス | 不適切な可視性タイムアウト、非同期プロセスの管理不備 |
| **Medium** | フロントエンド | メモリリークの可能性、状態管理の複雑化 |
| **Medium** | 全体 | 同期的な長時間処理、責務の巨大化 |
| **Low** | コード品質 | コードの重複、ロギングの不統一、テストカバレッジ不足 |

## 3. 主要な問題の詳細

### 3.1. データベース関連の問題 (Critical)

#### C1: SQL方言の混在

- **現象**: バックエンドAPI (`video.py`, `admin.py`) の一部で、`CREATE TABLE` 文に `AUTO_INCREMENT`, `ENUM`, `TINYINT` といったMySQL固有のSQL構文が使用されています。しかし、プロジェクトのデータベースはPostgreSQLであり、`asyncpg` ドライバが使用されているため、これらの構文はエラーを引き起こします。
- **リスク**: 本番環境や、ローカルでもPostgreSQLを使用する環境でデプロイに失敗するか、実行時エラーが発生します。データベーススキーマの一貫性が損なわれます。
- **該当箇所**: `backend/app/api/v1/endpoints/video.py` (例: `replace-excel`エンドポイント), `backend/app/api/v1/endpoints/admin.py` (例: `log-csv-validation`エンドポイント)

#### C2: 不適切なトランザクションとコネクション管理

- **現象**: `worker/batch/db_ops.py` 内の多くの関数が、トランザクションの自動コミット・ロールバックを保証する `get_session()` コンテキストマネージャを使用せず、`AsyncSessionLocal()` を直接使用しています。これにより、例外発生時にロールバックが実行されず、データ不整合が発生する可能性があります。また、`backend/app/api/v1/endpoints/chat.py` では、`psycopg2` を直接使用して同期的にDB接続を行っており、`asyncpg` 用に設定されたコネクションプーリングの恩恵を受けられません。
- **リスク**: データ不整合、コネクションリークによるパフォーマンス低下、データベース接続数の枯渇。
- **該当箇所**: `worker/batch/db_ops.py` 全体, `backend/app/api/v1/endpoints/chat.py` (`_bg_save_sync` 関数)

#### C3: N+1クエリ問題

- **現象**: `worker/batch/process_video.py` の `build_phase_units` 後の処理で、`phase_units` のリストをループし、各フェーズ (`p`) ごとにDB更新 (`update_video_phase_*_sync`) を行っています。これにより、フェーズ数に応じた大量のUPDATE文が個別に発行され、パフォーマンスが著しく低下します。
- **リスク**: ビデオのフェーズ数が多い場合、データベースへの負荷が急増し、処理時間が大幅に増加します。
- **該当箇所**: `worker/batch/process_video.py` (STEP 5以降のループ内DB更新)

### 3.2. バックエンドAPIとWorkerプロセスの問題 (Critical/High)

#### H1: 不十分なエラーハンドリング

- **現象**: `backend/app/api/v1/endpoints/video.py` をはじめ、多くのAPIエンドポイントでトップレベルの `try...except` ブロックが欠落しています。予期せぬ例外が発生した場合、適切なエラーレスポンスが返されず、サーバーがクラッシュする可能性があります。
- **リスク**: サーバーの可用性低下、クライアント側でのハンドリング困難、デバッグの複雑化。
- **該当箇所**: `video.py`, `clip_editor_v2.py` などの多くのエンドポイント。

#### H2: Workerプロセスの堅牢性の欠如

- **現象**: `worker/entrypoints/queue_worker.py` では、Azure Queue Storageのメッセージの可視性タイムアウトが15分に設定されているのに対し、その更新間隔は5分です。動画処理のような長時間タスクが15分を超えると、同じメッセージが再度キューに現れ、別のWorkerによって二重処理される可能性があります。また、`process_video.py` では `subprocess.Popen` で非同期プロセスを起動していますが、プロセスの死活監視やエラーハンドリングが不十分で、ゾンビプロセスが発生するリスクがあります。
- **リスク**: 同一ジョブの重複実行によるリソースの無駄遣いやデータ不整合。システム内にゾンビプロセスが蓄積し、リソースを枯渇させる可能性。
- **該当箇所**: `worker/entrypoints/queue_worker.py`, `worker/batch/process_video.py` (`fire_split_async`, `fire_compress_async`)

### 3.3. コード品質と保守性の問題 (Medium/Low)

#### M1: フロントエンドのメモリリーク

- **現象**: `videoService.js` の `streamVideoStatus` 関数では、`fetch` を用いたServer-Sent Events (SSE) 接続を確立していますが、コンポーネントのアンマウント時に `controller.abort()` を呼び出すクリーンアップ処理が、呼び出し側 (`MainContent.jsx` など) で実装されていません。これにより、ページ遷移後もバックグラウンドで接続が維持され、メモリリークを引き起こす可能性があります。
- **リスク**: アプリケーション全体のパフォーマンス低下、ブラウザのクラッシュ。
- **該当箇所**: `frontend/src/base/services/videoService.js`, `frontend/src/components/MainContent.jsx`

#### M2: 巨大すぎるコンポーネントと責務分離

- **現象**: `backend/app/api/v1/endpoints/video.py` (4800行以上)、`worker/batch/process_video.py` (1700行以上)、`frontend/src/components/ClipEditorV2.jsx` (2000行以上) など、単一のファイルが極端に巨大化しています。`get_video_detail` エンドポイントのように、1つの関数が300行を超え、多数の責務を抱えています。
- **リスク**: コードの可読性と保守性が著しく低い。修正による影響範囲の特定が困難で、デグレードのリスクが高い。

#### M3: 同期的な長時間処理

- **現象**: `backfill_sales_moments` APIエンドポイントは、リクエスト処理の過程で外部URLからファイルをダウンロードし、パースし、多数のDB書き込みを行うなど、潜在的に時間のかかる処理を同期的に実行しています。これにより、HTTPリクエストがタイムアウトする可能性があります。
- **リスク**: APIのタイムアウトエラー、ユーザー体験の悪化。
- **該当箇所**: `backend/app/api/v1/endpoints/video.py` (`backfill_sales_moments`)

## 4. 推奨されるリファクタリング計画

上記の問題を解決し、システムの安定性と保守性を向上させるために、以下の段階的なリファクタリング計画を提案します。

### Phase 1: 緊急対応 (Critical)

1.  **SQL方言の統一**: `video.py` と `admin.py` 内の `CREATE TABLE` 文をPostgreSQL互換の構文 (`SERIAL` または `BIGSERIAL`, `TEXT`, `BOOLEAN` など) に修正します。
2.  **トランザクション管理の修正**: `worker/batch/db_ops.py` 内のすべてのDB操作が `get_session()` コンテキストマネージャを使用するようにリファクタリングします。`chat.py` のDB書き込みも非同期の `db_ops` を利用するように変更します。
3.  **APIエラーハンドリングの追加**: `try...except` ブロックが欠落しているすべてのAPIエンドポイントに、包括的なエラーハンドリングを追加します。

### Phase 2: 安定性向上 (High/Medium)

1.  **Workerの堅牢性強化**: `queue_worker.py` の可視性タイムアウト更新ロジックを見直し、処理時間に応じてタイムアウトを動的に延長する、または更新間隔を短くするなどの対策を講じます。`subprocess.Popen` で起動したプロセスの監視と、異常終了時の再起動や通知の仕組みを導入します。
2.  **N+1クエリの解消**: `process_video.py` のループ内DB更新を、単一のバルクアップデート処理に置き換えます。
3.  **フロントエンドのメモリリーク修正**: `streamVideoStatus` を呼び出しているコンポーネントで、`useEffect` のクリーンアップ関数内で `stream.close()` を呼び出すように修正します。

### Phase 3: 保守性向上 (Medium/Low)

1.  **巨大ファイルの分割**: `video.py`, `process_video.py` などの巨大なファイルを、責務に基づいて複数の小さなファイルに分割します。（例: `video.py` → `video_routes.py`, `clip_routes.py`, `phase_routes.py` など）
2.  **長時間処理の非同期化**: `backfill_sales_moments` のような重い処理をバックグラウンドタスクに切り出し、APIは即座にジョブ受付レスポンスを返すように変更します。
3.  **コード品質の改善**: プロジェクト全体で `print` 文を `logger` に置き換え、linterを導入して未使用のimportなどを自動的に検出・修正する仕組みを整えます。
4.  **テストカバレッジの向上**: 特にビジネスロジックが集中している箇所や、今回修正を加える箇所を中心に、単体テストと結合テストを追加します。
