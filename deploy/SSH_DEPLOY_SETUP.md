# AitherHub Worker SSH Deploy セットアップ

## 必要な GitHub Secrets

以下の3つを GitHub リポジトリの Settings → Secrets and variables → Actions に設定してください。

| Secret 名 | 内容 | 例 |
|---|---|---|
| `WORKER_SSH_HOST` | Worker VM の IP アドレスまたはホスト名 | `20.xxx.xxx.xxx` |
| `WORKER_SSH_USER` | SSH ログインユーザー名 | `azureuser` |
| `WORKER_SSH_KEY` | SSH 秘密鍵（PEM形式、全文） | `-----BEGIN OPENSSH PRIVATE KEY-----` ... |

## GitHub Secrets 設定手順

### 1. SSH鍵ペアの作成（まだない場合）

VM上で実行します。

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
```

公開鍵をauthorized_keysに追加します。

```bash
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
```

秘密鍵の内容を取得します。

```bash
cat ~/.ssh/github_deploy
```

### 2. GitHub に Secrets を登録

GitHub CLI を使う場合は以下のコマンドで設定できます。

```bash
gh secret set WORKER_SSH_HOST --body "VMのIPアドレス"
gh secret set WORKER_SSH_USER --body "azureuser"
gh secret set WORKER_SSH_KEY < ~/.ssh/github_deploy
```

GitHub Web UI を使う場合は以下の手順です。

1. `https://github.com/LCJ-Group/aitherhub/settings/secrets/actions` を開く
2. 「New repository secret」をクリック
3. 各 Secret を1つずつ登録

### 3. VM 側の準備

リポジトリが `/opt/aitherhub` にクローンされていることを確認します。

```bash
ls /opt/aitherhub/.git
```

もしまだなら以下を実行します。

```bash
sudo git clone https://github.com/LCJ-Group/aitherhub.git /opt/aitherhub
sudo chown -R azureuser:azureuser /opt/aitherhub
```

systemd サービスが登録されていることを確認します。

```bash
sudo cp /opt/aitherhub/deploy/simple-worker.service /etc/systemd/system/aither-worker.service
sudo systemctl daemon-reload
sudo systemctl enable aither-worker
```

## デプロイの流れ

```
git push (master)
    ↓
GitHub Actions 起動
    ↓
SSH で VM に接続
    ↓
git pull
    ↓
pip install
    ↓
systemctl restart aither-worker
    ↓
commit 検証
    ↓
health check
```

## 手動デプロイ

VM に SSH して以下を実行します。

```bash
sudo bash /opt/aitherhub/deploy/deploy.sh
```

## ロールバック

デプロイ後に問題が発生した場合、VM に SSH して以下を実行します。

```bash
# 1つ前のcommitに戻す
sudo bash /opt/aitherhub/deploy/rollback.sh

# 特定のcommitに戻す
sudo bash /opt/aitherhub/deploy/rollback.sh abc1234
```
