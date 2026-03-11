# 圧縮スタック問題 - 修正計画

## 確定した根本原因

### 1. UIが「uploaded」を「圧縮中」と表示する
- normalizeProcessingStatus: `uploaded` → `STEP_COMPRESS_1080P`
- analysisSteps[0]: `STEP_COMPRESS_1080P` → 「動画を1080pに圧縮中...」
- **実際には圧縮はバックグラウンドで実行され、メインパイプラインはすぐにSTEP_0に進む**
- DBステータスが`uploaded`のままということは、Workerがまだ開始していないか、開始直後にクラッシュ

### 2. retry_analysisがERROR時に`uploaded`にリセットする
- retry_analysis: ERROR → `uploaded` にリセット → UIは再び「圧縮中」と表示
- Workerが再度クラッシュすると、同じ「圧縮中」ループに陥る

### 3. compress_to_1080pにタイムアウトがない
- ffmpegのsubprocess.runにtimeoutなし
- 大きなファイルで無限ハングの可能性（ただし別プロセスなので直接の原因ではない）

## 修正内容

### Fix 1: UIのステータス表示を改善
- `uploaded` → `STEP_COMPRESS_1080P` のマッピングを削除
- 代わりに `uploaded` → `QUEUED` として「キュー待ち」と表示
- 実際の圧縮はバックグラウンドで行われるため、ユーザーに「圧縮中」と見せるのは誤解を招く

### Fix 2: process_video.pyの早期ステータス更新
- ダウンロード開始前にステータスを`STEP_0_EXTRACT_FRAMES`に更新
- これにより、Workerが開始した時点でUIが「フレーム抽出中」に進む

### Fix 3: compress_to_1080pにタイムアウト追加
- 最大3時間のタイムアウトを設定
- タイムアウト時はffmpegプロセスをkill

### Fix 4: stuck_video_monitorの改善
- worker_guardを3時間→1時間に短縮
- CHECK_INTERVAL_MINUTESを5分→3分に短縮

### Fix 5: retry_analysisの改善
- ERRORからのリトライ時、`uploaded`ではなく`QUEUED`にリセット
