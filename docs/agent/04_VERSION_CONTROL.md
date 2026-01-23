# 成果物のVersion管理

## 概要

Agentが生成した成果物（コード、アセット、ドキュメント）をバージョン管理し、任意の時点にロールバック可能にする。
コードはGit、バイナリアセットはDVC（Data Version Control）で管理する。

## 成果物の種類と管理方法

| 種類 | 例 | 管理方法 |
|------|-----|---------|
| コード | .py, .ts, .cs | Git |
| テキストアセット | .json, .yaml, .md | Git |
| 画像 | .png, .jpg, .webp | DVC |
| 音声 | .mp3, .wav, .ogg | DVC |
| 3Dモデル | .fbx, .glb | DVC |
| ビルド成果物 | .exe, .apk | DVC |

## Gitリモート設定

### git_configテーブル

| カラム | 型 | 説明 |
|--------|-----|------|
| id | INTEGER | 主キー |
| project_id | TEXT | プロジェクトID |
| remote_url | TEXT | リモートリポジトリURL |
| remote_name | TEXT | リモート名（デフォルト: origin） |
| default_branch | TEXT | デフォルトブランチ（main等） |
| auth_method | TEXT | 認証方式（ssh/token/none） |
| credential_key | TEXT | 認証情報へのキー |
| dvc_remote_url | TEXT | DVCリモートURL |
| dvc_remote_type | TEXT | DVCリモート種別（s3/gcs/azure/local） |

### WebUI設定画面

| 設定項目 | 説明 |
|---------|------|
| リモートURL | GitHub/GitLab等のリポジトリURL |
| 認証方式 | SSH鍵 / Personal Access Token |
| デフォルトブランチ | main / master 等 |
| DVCリモートURL | S3/GCS等のストレージURL |

## フォルダ構造

| パス | 用途 |
|------|------|
| projects/{project_id}/repo/ | Gitリポジトリ（コード） |
| projects/{project_id}/repo/.dvc/ | DVC設定 |
| projects/{project_id}/repo/assets/ | DVCトラッキング対象 |
| projects/{project_id}/dvc_cache/ | DVCキャッシュ（ローカル） |

## Gitによるコード管理

### ブランチ戦略

| ブランチ | 用途 |
|---------|------|
| main | メインブランチ |
| session/{session_id} | セッションブランチ |
| task/{task_id} | タスクブランチ |
| release/v{version} | リリースブランチ |

### コミット規則

| type | 説明 |
|------|------|
| feat | 新機能 |
| fix | バグ修正 |
| refactor | リファクタリング |
| asset | アセット追加 |
| test | テスト追加 |

フォーマット: `{type}({scope}): {description}`

### WORKERのGit操作

1. タスク開始時: task/{task_id} ブランチ作成
2. 変更時: git add + commit
3. タスク完了時: mainにマージ、ブランチ削除

## DVCによるバイナリアセット管理

### DVCとは

DVC（Data Version Control）はGitと連携してバイナリファイルをバージョン管理するツール。
ファイルの実体はリモートストレージに保存し、Gitにはメタデータ（.dvcファイル）のみをコミットする。

### DVC操作

| 操作 | 説明 |
|------|------|
| dvc init | DVC初期化 |
| dvc add {file} | アセットをトラッキングに追加 |
| dvc push | リモートストレージにプッシュ |
| dvc pull | リモートストレージからプル |
| dvc diff | バージョン間の差分取得 |
| dvc checkout | 指定リビジョンをチェックアウト |

## タスク完了時のフロー

1. バイナリアセットをDVCに追加
2. Gitコミット
3. タスク完了（マージ）
4. リモートにプッシュ（Git + DVC）

## WebUI連携

### バージョン一覧画面

| 表示項目 | 説明 |
|---------|------|
| コミットハッシュ | Gitコミットの短縮ハッシュ |
| 日時 | コミット日時 |
| メッセージ | コミットメッセージ |
| 変更ファイル | 変更されたファイル一覧 |
| アセット変更 | DVCで管理されたアセットの変更 |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/versions | バージョン一覧（Gitログ） |
| GET | /projects/{id}/versions/{hash} | バージョン詳細 |
| POST | /projects/{id}/checkout | 指定バージョンをチェックアウト |
| GET | /projects/{id}/diff | 差分取得 |
| GET | /projects/{id}/assets | アセット一覧（DVC管理） |
