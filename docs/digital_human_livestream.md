# 數智人直播 API 対接モジュール (PoC)

## 概要

本モジュールは AitherHub と騰訊雲智能數智人（Tencent Cloud IVH）直播 API を対接し、AitherHub の動画分析結果から AI デジタルヒューマンのライブ配信台本を自動生成する PoC 実装です。

AitherHub が蓄積するライブコマース分析データ（フェーズ分析、売上指標、音声書き起こし、インサイト）を活用し、高パフォーマンスのフェーズを優先的に台本に反映することで、データドリブンなライブ配信を実現します。

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                    AitherHub Backend                      │
│                                                           │
│  ┌──────────────┐    ┌───────────────────┐               │
│  │ Digital Human │    │  Script Generator │               │
│  │  Endpoints    │───▶│    Service        │               │
│  │  (FastAPI)    │    │  (LLM-powered)    │               │
│  └──────┬───────┘    └────────┬──────────┘               │
│         │                     │                           │
│         │              ┌──────▼──────────┐               │
│         │              │  AitherHub DB    │               │
│         │              │  (phases, GMV,   │               │
│         │              │   insights, STT) │               │
│         │              └─────────────────┘               │
│         │                                                 │
│  ┌──────▼──────────────────┐                             │
│  │ Tencent Digital Human   │                             │
│  │ Service (API Client)    │                             │
│  │  - HMAC-SHA256 signing  │                             │
│  │  - HTTP client (httpx)  │                             │
│  └──────┬──────────────────┘                             │
└─────────┼─────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────┐
│  Tencent Cloud IVH API  │
│  gw.tvs.qq.com          │
│  - Open Liveroom        │
│  - Get Liveroom         │
│  - List Liverooms       │
│  - Takeover             │
│  - Close Liveroom       │
└─────────────────────────┘
```

## ファイル構成

| ファイル | 説明 |
|---------|------|
| `backend/app/services/tencent_digital_human_service.py` | 騰訊雲 IVH API クライアント（署名生成、全5エンドポイント対応） |
| `backend/app/services/script_generator_service.py` | 台本自動生成サービス（分析データ取得、フェーズスコアリング、LLM台本生成） |
| `backend/app/api/v1/endpoints/digital_human.py` | FastAPI エンドポイント（6つのAPI） |
| `backend/app/schemas/digital_human_schema.py` | Pydantic リクエスト/レスポンススキーマ |
| `tests/test_digital_human.py` | ユニットテスト（21テスト） |

## API エンドポイント

すべてのエンドポイントは `X-Admin-Key: aither:hub` ヘッダーが必要です。

### 1. 直播間作成

分析データから台本を自動生成し、直播間を作成します。

```
POST /api/v1/digital-human/liveroom/create
```

**リクエスト例（分析データから自動生成）:**

```json
{
  "video_id": "abc-123-def",
  "cycle_times": 5,
  "protocol": "rtmp",
  "product_focus": "KYOGOKU シグネチャーシャンプー",
  "tone": "professional_friendly",
  "language": "ja"
}
```

**リクエスト例（手動台本）:**

```json
{
  "scripts": ["皆さん、こんにちは！今日は特別な商品をご紹介します..."],
  "cycle_times": 3,
  "protocol": "rtmp"
}
```

**レスポンス:**

```json
{
  "success": true,
  "liveroom_id": "lr_abc123",
  "status": 0,
  "status_label": "INITIAL",
  "req_id": "d7aa08da33dd4a662ad5be508c5b77cf",
  "script_preview": "皆さん、こんにちは！..."
}
```

### 2. 直播間ステータス照会

```
GET /api/v1/digital-human/liveroom/{liveroom_id}
```

ステータスコードの意味は以下の通りです。

| Status | Label | 説明 |
|--------|-------|------|
| 0 | INITIAL | 初期化中 |
| 1 | STREAM_CREATING | ストリーム作成中 |
| 2 | STREAM_READY | ストリーム準備完了（配信開始可能） |
| 3 | SCRIPT_SPLIT_DONE | 台本分割完了 |
| 4 | SCHEDULING | スケジューリング中 |
| 5 | SCHEDULE_DONE | スケジューリング完了 |
| 6 | CLOSED | 閉鎖済み |

### 3. 直播間一覧

```
GET /api/v1/digital-human/liverooms?page_size=20&page_index=1
```

v5.x.x プロトコルでは `PageIndex`（1始まり）と `PageSize`（1-1000）を使用します。

### 4. 即時挿播（Takeover）

直播中にリアルタイムでテキストを挿入し、數智人に即座に読み上げさせます。

```
POST /api/v1/digital-human/liveroom/{liveroom_id}/takeover
```

**リクエスト例（直接テキスト）:**

```json
{
  "content": "皆さん、今だけ特別価格です！残り10個！"
}
```

**リクエスト例（AI自動生成）:**

```json
{
  "event_context": "商品Aが直近5分で50個売れました",
  "event_type": "engagement_spike",
  "language": "ja"
}
```

### 5. 直播間閉鎖

```
POST /api/v1/digital-human/liveroom/{liveroom_id}/close
```

### 6. 台本プレビュー生成（直播間を作成せずに台本のみ生成）

```
POST /api/v1/digital-human/script/generate
```

```json
{
  "video_id": "abc-123-def",
  "product_focus": "KYOGOKU シグネチャーシャンプー",
  "tone": "energetic",
  "language": "ja"
}
```

## 台本自動生成ロジック

台本生成は以下のステップで行われます。

**Step 1: データ取得** — AitherHub DB から対象動画の分析データ（phases, insights, speech_segments, reports）を取得します。

**Step 2: フェーズスコアリング** — 各フェーズを以下の重み付けでスコアリングし、高パフォーマンスのフェーズを優先します。

| 指標 | 重み | 説明 |
|------|------|------|
| GMV | 40% | 売上金額 |
| Delta View | 25% | 視聴者増加数 |
| Delta Like | 15% | いいね増加数 |
| CTA Score | 20% | CTA効果スコア |

**Step 3: LLM台本生成** — GPT-4.1-mini を使用して、トップパフォーマンスフェーズの内容、元の配信者の話し方、分析インサイトを参考に、數智人向けの台本を生成します。

**Step 4: フォールバック** — LLM が利用できない場合、フェーズ説明と音声テキストから簡易台本を構築します。

## 声音复刻（カスタムボイス）

自分の声で數智人を駆動する場合、`speech_param` に `timbre_key` を指定します。

```json
{
  "video_id": "abc-123-def",
  "speech_param": {
    "speed": 1.0,
    "timbre_key": "your-cloned-voice-id",
    "volume": 0,
    "pitch": 0.0
  }
}
```

`timbre_key` は騰訊雲の声音复刻サービスで取得できます。

## 環境変数

`.env` に以下の変数を設定してください。

```
TENCENT_IVH_BASE_URL=https://gw.tvs.qq.com
TENCENT_IVH_APPKEY=your-appkey
TENCENT_IVH_ACCESS_TOKEN=your-access-token
TENCENT_IVH_PROJECT_ID=your-virtualman-project-id
TENCENT_IVH_PROTOCOL=rtmp
```

**v5.x.x プロトコル**を使用しています。AppKey と AccessToken は[騰訊雲數智人平台の資源管理中心](https://ivh.cloud.tencent.com/management/resource)から取得できます。

### 必要な腾讯云资源

| 资源 | 说明 | 必须 |
|------|------|------|
| 形象定制/租赁 | 数智人の外見 | ✅ |
| 会话互动并发数（云渲染场景） | 直播に必要な並行配額 | ✅ |
| 声音复刻 | カスタムボイス | 任意 |

## テスト

```bash
cd /path/to/aitherhub
PYTHONPATH=backend python3 -m pytest tests/test_digital_human.py -v
```

## 今後の拡張計画

本 PoC を基に、以下の機能拡張を予定しています。

1. **リアルタイム分析連携**: AitherHub のライブ分析パイプラインと連携し、配信中のエンゲージメントデータに基づいて自動的に Takeover を発動する機能
2. **台本テンプレート管理**: 商品カテゴリ別の台本テンプレートを DB で管理し、分析データと組み合わせて最適な台本を生成
3. **A/B テスト**: 異なる台本バリエーションの配信パフォーマンスを比較し、最適な台本パターンを学習
4. **コールバック処理**: 騰訊雲からのコールバック通知を受信し、直播間のステータス変更を自動処理
5. **フロントエンド UI**: 管理ダッシュボードに數智人直播管理画面を追加
