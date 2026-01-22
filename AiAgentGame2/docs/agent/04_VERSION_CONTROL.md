# 成果物のVersion管理

## 概要

Agentが生成した成果物（コード、アセット、ドキュメント）をバージョン管理し、任意の時点にロールバック可能にする。
コードはGit、バイナリアセットはタイムスタンプ付きフォルダで管理する。

## 成果物の種類と管理方法

| 種類 | 例 | 管理方法 |
|------|-----|---------|
| コード | .py, .ts, .cs | Git |
| テキストアセット | .json, .yaml, .md | Git |
| 画像 | .png, .jpg, .webp | フォルダ + manifest.json |
| 音声 | .mp3, .wav, .ogg | フォルダ + manifest.json |
| 3Dモデル | .fbx, .glb | フォルダ + manifest.json |
| ビルド成果物 | .exe, .apk | フォルダ + manifest.json |

## フォルダ構造

```
projects/{project_id}/
├── repo/                         # Gitリポジトリ（コード）
│   ├── .git/
│   ├── src/
│   └── ...
│
├── artifacts/                    # バイナリアセット
│   ├── versions/
│   │   ├── v001/
│   │   │   ├── manifest.json
│   │   │   ├── images/
│   │   │   ├── audio/
│   │   │   └── models/
│   │   ├── v002/
│   │   └── v003/
│   ├── latest -> versions/v003/  # シンボリックリンク
│   └── version_history.json
│
└── builds/                       # ビルド成果物
    ├── v001/
    ├── v002/
    └── latest -> v002/
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

## バイナリアセットの管理

### manifest.json

```json
{
  "version": "v003",
  "created_at": "2024-01-15T16:00:00Z",
  "created_by": "worker_asset_001",
  "parent_version": "v002",
  "description": "プレイヤーキャラクターの画像を追加",

  "assets": [
    {
      "id": "asset_001",
      "path": "images/player.png",
      "type": "image",
      "size_bytes": 102400,
      "hash": "sha256:abc123...",
      "metadata": {
        "width": 256,
        "height": 256,
        "format": "PNG"
      },
      "created_by_task": "task_p2_asset_001"
    },
    {
      "id": "asset_002",
      "path": "audio/jump.mp3",
      "type": "audio",
      "size_bytes": 51200,
      "hash": "sha256:def456...",
      "metadata": {
        "duration_ms": 500,
        "sample_rate": 44100
      },
      "created_by_task": "task_p2_asset_002"
    }
  ],

  "changes": [
    {"action": "add", "asset_id": "asset_001"},
    {"action": "add", "asset_id": "asset_002"}
  ]
}
```

### version_history.json

```json
{
  "current_version": "v003",
  "versions": [
    {
      "version": "v001",
      "created_at": "2024-01-15T14:00:00Z",
      "description": "初期アセット",
      "asset_count": 5
    },
    {
      "version": "v002",
      "created_at": "2024-01-15T15:00:00Z",
      "description": "敵キャラクター追加",
      "asset_count": 10
    },
    {
      "version": "v003",
      "created_at": "2024-01-15T16:00:00Z",
      "description": "プレイヤーキャラクター追加",
      "asset_count": 12
    }
  ]
}
```

## バージョン操作

### 新バージョン作成

```python
class ArtifactVersionManager:
    def __init__(self, artifacts_path: Path):
        self.artifacts_path = artifacts_path
        self.versions_path = artifacts_path / "versions"

    def create_version(self, description: str, assets: List[Asset]) -> str:
        """新しいバージョンを作成"""
        # 次のバージョン番号を取得
        current = self._get_current_version()
        new_version = f"v{int(current[1:]) + 1:03d}"

        # バージョンフォルダ作成
        version_path = self.versions_path / new_version
        version_path.mkdir(parents=True)

        # アセットをコピー
        for asset in assets:
            dest = version_path / asset.relative_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(asset.source_path, dest)

        # manifest.json作成
        manifest = self._create_manifest(new_version, description, assets)
        with open(version_path / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

        # latestリンク更新
        latest_link = self.artifacts_path / "latest"
        if latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(version_path)

        # version_history.json更新
        self._update_history(new_version, description, len(assets))

        return new_version
```

### ロールバック

```python
def rollback_to(self, target_version: str) -> None:
    """指定バージョンにロールバック"""
    target_path = self.versions_path / target_version

    if not target_path.exists():
        raise ValueError(f"Version {target_version} not found")

    # latestリンクを更新
    latest_link = self.artifacts_path / "latest"
    if latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(target_path)

    # version_history.jsonに記録
    self._record_rollback(target_version)

    # ロールバック後のバージョンを新バージョンとして作成（履歴を保持）
    # 例: v005からv003にロールバック → v006としてv003の内容をコピー
```

### 差分取得

```python
def get_diff(self, from_version: str, to_version: str) -> dict:
    """2つのバージョン間の差分を取得"""
    from_manifest = self._load_manifest(from_version)
    to_manifest = self._load_manifest(to_version)

    from_assets = {a["id"]: a for a in from_manifest["assets"]}
    to_assets = {a["id"]: a for a in to_manifest["assets"]}

    added = [a for id, a in to_assets.items() if id not in from_assets]
    removed = [a for id, a in from_assets.items() if id not in to_assets]
    modified = [
        a for id, a in to_assets.items()
        if id in from_assets and a["hash"] != from_assets[id]["hash"]
    ]

    return {
        "from_version": from_version,
        "to_version": to_version,
        "added": added,
        "removed": removed,
        "modified": modified
    }
```

## ストレージ最適化

### 重複排除

```python
def deduplicate_assets(self) -> int:
    """同一ハッシュのファイルをハードリンクに置換"""
    hash_to_path: Dict[str, Path] = {}
    saved_bytes = 0

    for version_path in self.versions_path.iterdir():
        manifest = self._load_manifest(version_path.name)
        for asset in manifest["assets"]:
            asset_path = version_path / asset["path"]
            asset_hash = asset["hash"]

            if asset_hash in hash_to_path:
                # 同一ハッシュが存在 → ハードリンクに置換
                saved_bytes += asset_path.stat().st_size
                asset_path.unlink()
                asset_path.hardlink_to(hash_to_path[asset_hash])
            else:
                hash_to_path[asset_hash] = asset_path

    return saved_bytes
```

### 古いバージョンの圧縮

```python
def archive_old_versions(self, keep_recent: int = 5) -> None:
    """古いバージョンをzip圧縮"""
    versions = sorted(self.versions_path.iterdir())

    for version_path in versions[:-keep_recent]:
        archive_path = self.artifacts_path / "archives" / f"{version_path.name}.zip"
        shutil.make_archive(archive_path.with_suffix(""), "zip", version_path)
        shutil.rmtree(version_path)
```

## WebUI連携

### バージョン一覧画面

| 表示項目 | 説明 |
|---------|------|
| バージョン番号 | v001, v002, ... |
| 作成日時 | タイムスタンプ |
| 説明 | 変更内容 |
| アセット数 | 含まれるアセット数 |
| サイズ | 合計サイズ |
| アクション | 詳細表示、ロールバック、ダウンロード |

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /projects/{id}/artifacts/versions | バージョン一覧 |
| GET | /projects/{id}/artifacts/versions/{v} | バージョン詳細 |
| POST | /projects/{id}/artifacts/rollback | ロールバック実行 |
| GET | /projects/{id}/artifacts/diff | 差分取得 |
| GET | /projects/{id}/artifacts/download/{v} | ダウンロード |
