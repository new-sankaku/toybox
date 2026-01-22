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

### リモートリポジトリ設定

プロジェクト作成時にGitリモートを設定する。

```sql
CREATE TABLE git_config (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    remote_url TEXT NOT NULL,
    remote_name TEXT DEFAULT 'origin',
    default_branch TEXT DEFAULT 'main',
    auth_method TEXT NOT NULL,  -- 'ssh', 'token', 'none'
    credential_key TEXT,         -- 認証情報へのキー（環境変数名等）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

### WebUI設定画面

| 設定項目 | 説明 |
|---------|------|
| リモートURL | GitHub/GitLab等のリポジトリURL |
| 認証方式 | SSH鍵 / Personal Access Token |
| デフォルトブランチ | main / master 等 |

### 初期化処理

```python
class GitRepoManager:
    def __init__(self, db: Database):
        self.db = db

    def init_repo(self, project_id: str, local_path: Path) -> None:
        """プロジェクト用Gitリポジトリを初期化"""
        config = self.db.get_git_config(project_id)

        # ローカルリポジトリ初期化
        subprocess.run(["git", "init"], cwd=local_path)

        # リモート設定
        if config.remote_url:
            subprocess.run(
                ["git", "remote", "add", config.remote_name, config.remote_url],
                cwd=local_path
            )

        # 初期コミット
        subprocess.run(["git", "add", "."], cwd=local_path)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=local_path)

    def push(self, local_path: Path, branch: str = None) -> None:
        """リモートにプッシュ"""
        config = self.db.get_git_config_by_path(local_path)
        branch = branch or config.default_branch
        subprocess.run(
            ["git", "push", "-u", config.remote_name, branch],
            cwd=local_path
        )
```

## フォルダ構造

```
projects/{project_id}/
├── repo/                         # Gitリポジトリ（コード）
│   ├── .git/
│   ├── .dvc/                     # DVC設定
│   ├── .dvcignore
│   ├── src/
│   ├── assets/                   # DVCトラッキング対象
│   │   ├── images/
│   │   │   └── player.png.dvc   # DVCメタファイル
│   │   ├── audio/
│   │   └── models/
│   └── ...
│
└── dvc_cache/                    # DVCキャッシュ（ローカル）
```

## Gitによるコード管理

### ブランチ戦略

```
main
  │
  ├── session/{session_id}      # セッションブランチ
  │     │
  │     ├── task/{task_id}      # タスクブランチ
  │     └── task/{task_id}
  │
  └── release/v{version}        # リリースブランチ
```

### コミット規則

```
# フォーマット
{type}({scope}): {description}

# type
- feat: 新機能
- fix: バグ修正
- refactor: リファクタリング
- asset: アセット追加
- test: テスト追加

# 例
feat(player): ジャンプ機能を実装
fix(enemy): 衝突判定のバグを修正
asset(ui): タイトル画面の画像を追加
```

### WORKERのGit操作

```python
class WorkerGitOps:
    def __init__(self, repo_path: str, task_id: str):
        self.repo_path = repo_path
        self.task_id = task_id
        self.branch_name = f"task/{task_id}"

    def start_task(self) -> None:
        """タスク開始時にブランチ作成"""
        subprocess.run(["git", "checkout", "-b", self.branch_name], cwd=self.repo_path)

    def commit_changes(self, message: str) -> None:
        """変更をコミット"""
        subprocess.run(["git", "add", "."], cwd=self.repo_path)
        subprocess.run(["git", "commit", "-m", message], cwd=self.repo_path)

    def complete_task(self) -> None:
        """タスク完了時にマージ"""
        subprocess.run(["git", "checkout", "main"], cwd=self.repo_path)
        subprocess.run(["git", "merge", self.branch_name], cwd=self.repo_path)
        subprocess.run(["git", "branch", "-d", self.branch_name], cwd=self.repo_path)
```

## DVCによるバイナリアセット管理

### DVCとは

DVC（Data Version Control）はGitと連携してバイナリファイルをバージョン管理するツール。
ファイルの実体はリモートストレージに保存し、Gitにはメタデータ（.dvcファイル）のみをコミットする。

### DVCリモート設定

```sql
-- git_configテーブルに追加
ALTER TABLE git_config ADD COLUMN dvc_remote_url TEXT;
ALTER TABLE git_config ADD COLUMN dvc_remote_type TEXT;  -- 's3', 'gcs', 'azure', 'local'
```

### 初期化

```python
class DVCManager:
    def __init__(self, repo_path: Path, db: Database):
        self.repo_path = repo_path
        self.db = db

    def init(self, project_id: str) -> None:
        """DVCを初期化"""
        config = self.db.get_git_config(project_id)

        # DVC初期化
        subprocess.run(["dvc", "init"], cwd=self.repo_path)

        # リモートストレージ設定
        if config.dvc_remote_url:
            subprocess.run([
                "dvc", "remote", "add", "-d", "storage", config.dvc_remote_url
            ], cwd=self.repo_path)

        # .dvcをGitにコミット
        subprocess.run(["git", "add", ".dvc", ".dvcignore"], cwd=self.repo_path)
        subprocess.run(["git", "commit", "-m", "Initialize DVC"], cwd=self.repo_path)
```

### アセット追加

```python
def add_asset(self, asset_path: Path) -> None:
    """アセットをDVCトラッキングに追加"""
    # DVCでトラッキング
    subprocess.run(["dvc", "add", str(asset_path)], cwd=self.repo_path)

    # .dvcファイルをGitにコミット
    dvc_file = asset_path.with_suffix(asset_path.suffix + ".dvc")
    subprocess.run(["git", "add", str(dvc_file)], cwd=self.repo_path)
```

### プッシュ・プル

```python
def push(self) -> None:
    """アセットをリモートストレージにプッシュ"""
    subprocess.run(["dvc", "push"], cwd=self.repo_path)

def pull(self) -> None:
    """アセットをリモートストレージからプル"""
    subprocess.run(["dvc", "pull"], cwd=self.repo_path)
```

### バージョン間の差分

```python
def diff(self, rev_a: str = "HEAD~1", rev_b: str = "HEAD") -> dict:
    """2つのバージョン間のアセット差分を取得"""
    result = subprocess.run(
        ["dvc", "diff", rev_a, rev_b, "--json"],
        cwd=self.repo_path,
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)
```

### ロールバック

```python
def checkout(self, revision: str) -> None:
    """指定リビジョンのアセットをチェックアウト"""
    # Gitで対象リビジョンに移動
    subprocess.run(["git", "checkout", revision], cwd=self.repo_path)
    # DVCでアセットを取得
    subprocess.run(["dvc", "checkout"], cwd=self.repo_path)
```

## タスク完了時のフロー

```python
class TaskCompletionHandler:
    def __init__(self, git_ops: WorkerGitOps, dvc_manager: DVCManager):
        self.git_ops = git_ops
        self.dvc_manager = dvc_manager

    def complete(self, task: Task, outputs: List[Path]) -> None:
        """タスク完了時の処理"""

        # バイナリアセットをDVCに追加
        for output in outputs:
            if self._is_binary_asset(output):
                self.dvc_manager.add_asset(output)

        # Gitコミット
        self.git_ops.commit_changes(f"feat({task.scope}): {task.objective}")

        # タスク完了（マージ）
        self.git_ops.complete_task()

        # リモートにプッシュ
        self.dvc_manager.push()

    def _is_binary_asset(self, path: Path) -> bool:
        binary_extensions = {'.png', '.jpg', '.webp', '.mp3', '.wav', '.fbx', '.glb'}
        return path.suffix.lower() in binary_extensions
```

## WebUI連携

### バージョン一覧画面

| 表示項目 | 説明 |
|---------|------|
| コミットハッシュ | Gitコミットの短縮ハッシュ |
| 日時 | コミット日時 |
| メッセージ | コミットメッセージ |
| 変更ファイル | 変更されたファイル一覧 |
| アセット変更 | DVCで管理されたアセットの変更 |
| アクション | 詳細表示、チェックアウト、差分表示 |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/versions | バージョン一覧（Gitログ） |
| GET | /projects/{id}/versions/{hash} | バージョン詳細 |
| POST | /projects/{id}/checkout | 指定バージョンをチェックアウト |
| GET | /projects/{id}/diff | 差分取得 |
| GET | /projects/{id}/assets | アセット一覧（DVC管理） |
