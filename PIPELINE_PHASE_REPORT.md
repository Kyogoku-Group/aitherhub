# AitherHub Phase 4: Video Processing Pipeline v1 完了報告書

## 目的

AitherHubを単なる動画処理ツールから、AIによる「Video Intelligence Engine」へと進化させるため、動画理解パイプラインのバージョン1を構築しました。このパイプラインは、アップロードされた動画を多層的に分析し、構造化された知見（シーン、発話内容、イベント、セールスモーメント）を自動で抽出します。

**パイプラインフロー:**
`video` → `scene detection` → `speech extraction` → `speech to text` → `transcript segmentation` → `event detection` → `sales moment detection` → `clip generation`

---

## 実装内容サマリー

### Task 1: Video Pipeline Framework

**実装概要:**
-   **`worker/pipeline/`** ディレクトリを新設し、パイプライン関連の全モジュールを集約しました。
-   **`pipeline_runner.py`**: 各処理ステップを順番に実行し、実行時間、成功、失敗を管理するオーケストレーターです。ステップの重要度（critical）に応じて、エラー発生時に処理を続行または停止する制御も行います。
-   **`pipeline_context.py`**: パイプラインの各ステップ間で共有される状態オブジェクトです。各ステップはコンテキストから必要な情報を読み取り、結果を書き込むことで、ステップ間の疎結合性を実現しています。

### Task 2-8: Pipeline Steps

各分析ステップを独立したモジュールとして **`worker/pipeline/pipeline_steps/`** 以下に実装しました。

1.  **`scene_detection.py`**: 動画を視覚的な区切りでシーンに分割します。`PySceneDetect`ライブラリを主に使用し、利用不可の場合はFFmpegによる代替処理を行います。
2.  **`speech_extraction.py`**: FFmpegを使用し、動画からWhisper APIに最適化された16kHzモノラルのWAV音声を抽出します。
3.  **`speech_to_text.py`**: OpenAI Whisper APIを利用して音声を高精度に文字起こしします。25MBを超える音声ファイルは自動で分割処理されます。
4.  **`transcript_segmentation.py`**: 文字起こし結果を、発話の切れ目やシーンの境界に基づいて意味のあるセグメントに分割・結合します。
5.  **`event_detection.py`**: セグメント化されたテキストから、キーワードマッチングとLLM（GPT-4.1-mini）を併用し、4種類のビジネスイベント（`product_show`, `price_mention`, `call_to_action`, `comment_reaction`）を検出します。
6.  **`sales_moment_detection.py`**: 検出されたイベントの密度、テキストの緊急性、LLMによるスコアリングを組み合わせ、動画内で最もコンバージョンに繋がりやすい「セールスモーメント」を特定・ランク付けします。
7.  **`clip_generator.py`**: ランク付けされたセールスモーメントに基づき、FFmpegを使用して9:16の縦型ショート動画を自動生成します。

### Task 9: Pipeline Metrics

**実装概要:**
-   **`pipeline_metrics.py`**: パイプライン全体の実行時間と、各ステップの処理時間を計測し、構造化ログとして出力する機能を実装しました。これにより、パフォーマンスのボトルネック分析が容易になります。

### Task 10: DB Schema

**実装概要:**
-   パイプラインの各ステップで抽出されたデータを永続化するため、以下の5つの新しいテーブルスキーマを定義し、マイグレーションスクリプトを作成しました。
    -   `video_scenes`
    -   `video_transcripts`
    -   `video_segments`
    -   `video_events`
    -   `video_sales_moments`
-   **`pipeline_db.py`**: 各ステップからこれらのテーブルに結果を書き込むための、同期DB操作ヘルパーを実装しました。

---

## 成果物一覧

### 1. Pipeline Framework
-   `worker/pipeline/pipeline_runner.py`
-   `worker/pipeline/pipeline_context.py`
-   `worker/pipeline/pipeline_db.py`
-   `worker/pipeline/pipeline_metrics.py`

### 2. Pipeline Steps
-   `worker/pipeline/pipeline_steps/scene_detection.py`
-   `worker/pipeline/pipeline_steps/speech_extraction.py`
-   `worker/pipeline/pipeline_steps/speech_to_text.py`
-   `worker/pipeline/pipeline_steps/transcript_segmentation.py`
-   `worker/pipeline/pipeline_steps/event_detection.py`
-   `worker/pipeline/pipeline_steps/sales_moment_detection.py`
-   `worker/pipeline/pipeline_steps/clip_generator.py`

### 3. データベースマイグレーション
-   `backend/migrations/add_pipeline_tables_v1.sql`

### 4. テスト
-   `tests/test_pipeline.py`: パイプラインのロジックと各ステップの単体動作を検証する統合テストです。

全てのコードは、CIルールである「`worker/`から`app/`をimport禁止」を遵守しています。これにより、システムの安定性と保守性が維持されます。
