# Worker/API分離リファクタリング完了報告書

## 1. はじめに

本ドキュメントは、`aitherhub`リポジトリにおける**WorkerとAPIのアーキテクチャ分離**に関するリファクタリング作業の完了報告です。ご指摘いただいた「WorkerがAPIアプリ全体に依存している」という根本的な問題を解決し、システムの安定性、独立性、保守性を大幅に向上させるための構造改革を実施しました。

**核心的な変更点：**
- **`shared`層の新設**: APIとWorker間のすべての共通ロジック（DB接続、設定、スキーマ等）を集約。
- **依存関係の厳格化**: WorkerとAPIが互いに直接importすることを禁止し、`shared`層を介してのみ連携する構造を強制。
- **Workerの独立起動**: WorkerをFastAPIアプリケーションとは完全に独立したプロセスとして起動するエントリーポイントを新設。

> **設計原則：「APIは“頭脳”、Workerは“工場”」**
> この原則に基づき、頭脳（API）は指示（ジョブのenqueue）のみを行い、工場（Worker）は製造（ジョブの実行）に専念するクリーンな分離を実現しました。

## 2. 新しいアーキテクチャ

リポジトリの構造は以下のように再編成されました。`shared`層がAPIとWorkerの間の緩衝材として機能します。

```mermaid
graph TD
    subgraph aitherhub-api-service (backend/app)
        A[API Endpoints]
        B[Services]
    end

    subgraph aitherhub-worker-service (worker)
        D[Entrypoints]
        E[Processors]
    end

    subgraph aitherhub-shared-layer (shared)
        S_DB[DB Session]
        S_Queue[Queue Client]
        S_Config[Configuration]
        S_Schemas[Data Schemas]
        S_Storage[Blob Storage]
    end

    A --> S_Queue
    B --> S_DB
    B --> S_Storage

    D --> S_Queue
    E --> S_DB
    E --> S_Storage

    style aitherhub-api-service fill:#e6f2ff,stroke:#b3d9ff
    style aitherhub-worker-service fill:#e6ffed,stroke:#b3ffc6
    style aitherhub-shared-layer fill:#fff2e6,stroke:#ffd9b3
```

### 依存関係の黄金律

この新しいアーキテクチャを維持するため、以下のルールが導入され、CIによって自動的に強制されます。

1.  `worker/` は `backend/app/` を **importしてはならない**。
2.  `backend/app/` は `worker/` を **importしてはならない**。
3.  `shared/` は `backend/app/` または `worker/` を **importしてはならない**。
4.  `worker/` と `backend/app/` は `shared/` を **importしてよい**。

## 3. 主な変更点と成果物

### 3.1. `shared`層の構築

APIとWorkerで共有されるべきすべてのロジックを`shared/`ディレクトリに集約しました。

| モジュール | パス | 目的 |
| :--- | :--- | :--- |
| **設定管理** | `shared/config/__init__.py` | `.env`からの環境変数読み込みを一本化。 |
| **DBセッション** | `shared/db/session.py` | APIとWorkerで共通の非同期DBエンジンとセッション管理を提供。 |
| **Queueクライアント** | `shared/queue/client.py` | Azure Queue Storageへの接続と操作（enqueue/dequeue）を共通化。 |
| **Blob Storage** | `shared/storage/blob.py` | Azure Blob Storageへの接続と操作（upload/SAS生成）を共通化。 |
| **データスキーマ** | `shared/schemas/` | `VideoStatus`, `ClipStatus`, 各種ジョブペイロードの型定義を共有。 |

### 3.2. Workerの独立化

- **新エントリーポイント**: `worker/entrypoints/queue_worker.py` を新設しました。これは `simple_worker.py` を完全に置き換える、FastAPI非依存の新しいメインプロセスです。
  - **起動コマンド**: `python -m worker.entrypoints.queue_worker`
- **依存関係のクリーンアップ**: Worker内のコードから `backend/app` への依存を完全に排除しました。

### 3.3. ジョブテーブルの正式化 (`video_clips`)

クリップ生成ジョブの状態を堅牢に管理するため、既存の`video_clips`テーブルを拡張しました。

- **DBマイグレーション**: `backend/migrations/add_clip_jobs_v1.sql` を作成。以下のカラムを追加します。
  - `attempt_count`, `max_attempts`: リトライ回数管理
  - `heartbeat_at`, `started_at`, `finished_at`: ジョブ実行時間のトラッキング
  - `worker_id`: 実行中ワーカーの識別子
  - `last_error_code`, `last_error_message`: エラー詳細の記録
- **状態管理ロジック**: `shared/schemas/clip_job.py` に、ジョブのクレーム、ステータス更新、ハートビート等のDB操作関数を実装しました。

### 3.4. ヘルスチェックとCIによる境界強制

- **Workerヘルスチェック**: `worker/entrypoints/health_check.py` を新設。Workerプロセスの死活、DB/Queue接続、ffmpegの可用性などを監視する軽量なHTTPサーバーです。
- **CIによる境界チェック**: `.github/workflows/check_boundaries.yml` を追加。コードがpushされるたびに、前述の「依存関係の黄金律」が破られていないかを自動的に検証します。

### 3.5. デプロイ設定

新しいWorkerプロセスをVM上で正しく管理するため、`systemd`のサービスファイルを作成しました。

- `deploy/simple-worker.service`: 新しい`queue_worker`を起動するためのサービスファイル。
- `deploy/worker-health.service`: ヘルスチェックサーバーを起動するためのサービスファイル。

## 4. 今後のステップ

1.  **データベースマイグレーションの適用**: `add_clip_jobs_v1.sql` を本番およびステージング環境のDBに適用してください。
2.  **デプロイメントの更新**: VMのデプロイスクリプトを更新し、古い起動方法から新しい`systemd`サービス (`simple-worker.service`, `worker-health.service`) を利用するように変更してください。
3.  **段階的なリファクタリング**: `worker/batch/` 内の古いスクリプト (`generate_clip.py`など) は、今回作成した`shared`層のモジュールを利用するように段階的にリファクタリングを進めることを推奨します。

## 5. 結論

今回のリファクタリングにより、WorkerとAPIはアーキテクチャレベルで完全に分離されました。これにより、片方のサービスの障害がもう一方に波及するリスクが構造的に排除され、各コンポーネントを独立してスケール、デプロイ、監視することが可能になりました。これは、今後の開発速度とシステム全体の安定性に対する大きな投資となります。

ご提案いただいた明確なビジョンのおかげで、迅速かつ的確な改善を実施することができました。ありがとうございました。
