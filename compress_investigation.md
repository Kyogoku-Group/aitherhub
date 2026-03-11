# 圧縮ステップスタック問題の調査結果

## 問題の症状
- 動画が「動画を1080pに圧縮中...」で16時間以上スタック
- 進捗が4-5%で止まる
- stuck_video_monitorがリキューしても同じ状態に戻る

## 根本原因の分析

### 1. 圧縮はバックグラウンドプロセスだが、UIは圧縮ステータスを表示し続ける
- `fire_compress_async()` は `subprocess.Popen` で別プロセスとして起動
- **stdout/stderrはDEVNULLに捨てている** → ログが一切取れない
- compress_background.py → video_compressor.py → compress_to_1080p()
- ffmpegの `subprocess.run()` に **タイムアウトなし** (コメント: "No timeout - compression of large files can take hours")

### 2. UIのステータスの問題
- `STEP_COMPRESS_1080P` ステータスは process_video.py の line 206 で処理
- status == STEP_COMPRESS_1080P の場合、start_step = 0 にリセットされる
- つまり、圧縮中にスタックしてリキューされると、**最初からやり直し**になる

### 3. stuck_video_monitorの問題
- `worker_claimed_at` が3時間以内ならスキップする
- 圧縮プロセスが別プロセスで走っている間、メインのprocess_video.pyは先に進んでいる
- **圧縮はバックグラウンドなので、メインパイプラインのステータスは先に進むはず**
- しかし、UIは「圧縮中」と表示し続けている → **フロントエンドのステータス表示の問題？**

### 4. 重要な発見
- compress_background.py は **DBのステータスを更新しない**
- メインパイプラインは圧縮を待たずに STEP_0 (フレーム抽出) に進む
- しかし、UIが「圧縮中」と表示しているということは：
  - a) メインパイプラインが STEP_0 に進む前にクラッシュしている
  - b) または、ステータスが STEP_COMPRESS_1080P のまま更新されていない

### 5. ステータス遷移の問題
- line 620-623: `if start_step <= 0:` の場合に圧縮を起動
- line 631: `update_video_status_sync(video_id, VideoStatus.STEP_0_EXTRACT_FRAMES)` 
- **圧縮起動後すぐにSTEP_0に進むはず**
- もしSTEP_0への更新が失敗していたら、ステータスは前のままになる

### 結論
UIが「圧縮中」と表示しているのは、フロントエンドのProcessingSteps.jsxの
ステップ表示ロジックの問題。バックエンドのステータスは実際にはSTEP_0以降に
進んでいるか、エラーで止まっている可能性が高い。
