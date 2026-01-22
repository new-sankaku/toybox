# ログシステムの改良

## 概要

ログをAgent単位、グループ単位、Task単位で閲覧できるようにする。
従来のファイル形式のログに加え、構造化されたログを提供する。

## ログの階層

```
logs/
├── orchestrator/              # ORCHESTRATOR レベル
│   └── orchestrator.log
│
├── directors/                 # DIRECTOR レベル
│   ├── phase1_director.log
│   ├── phase2_director.log
│   └── phase3_director.log
│
├── leaders/                   # LEADER レベル
│   ├── concept_leader.log
│   ├── design_leader.log
│   ├── code_leader.log
│   └── ...
│
├── workers/                   # WORKER レベル
│   ├── worker_task_001.log
│   ├── worker_task_002.log
│   └── ...
│
├── tasks/                     # タスク単位（横断的）
│   ├── task_p1_concept_001.log
│   ├── task_p2_code_001.log
│   └── ...
│
├── groups/                    # グループ単位（集約）
│   ├── phase1.log
│   ├── phase2_code.log
│   ├── phase2_asset.log
│   └── phase3.log
│
└── combined/                  # 全体ログ
    └── all.log
```

## ログエントリ形式

### 構造化ログ（JSON）

```json
{
  "timestamp": "2024-01-15T14:30:00.123Z",
  "level": "INFO",
  "session_id": "sess_20240115143000_x1y2z3",
  "project_id": "proj_20240115_a1b2c3",

  "agent": {
    "role": "WORKER",
    "type": "code",
    "id": "worker_task_p2_code_003"
  },

  "task": {
    "id": "task_p2_code_003",
    "name": "PlayerController ジャンプ実装",
    "phase": 2
  },

  "group": "phase2/code",

  "message": "ジャンプ機能の実装を完了",

  "details": {
    "files_modified": ["src/Player/PlayerController.cs"],
    "lines_added": 45,
    "lines_removed": 0
  },

  "metrics": {
    "tokens_used": 1500,
    "duration_ms": 45000,
    "llm_model": "haiku",
    "cost_usd": 0.002
  }
}
```

### 人間可読ログ（テキスト）

```
2024-01-15 14:30:00.123 [INFO] [WORKER:code:worker_task_p2_code_003] [task_p2_code_003]
  ジャンプ機能の実装を完了
  files: src/Player/PlayerController.cs (+45 lines)
  duration: 45s, tokens: 1500, cost: $0.002
```

## ログレベル

| レベル | 用途 | 例 |
|--------|------|-----|
| DEBUG | 詳細なデバッグ情報 | 変数値、内部状態 |
| INFO | 通常の動作情報 | タスク開始/完了 |
| WARN | 警告（動作は継続） | リトライ発生、性能低下 |
| ERROR | エラー（タスク失敗） | 実行エラー、検証失敗 |
| FATAL | 致命的エラー（停止） | システムエラー |

## ログ収集

### Logger クラス

```python
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

class StructuredLogger:
    def __init__(
        self,
        logs_dir: Path,
        session_id: str,
        project_id: str
    ):
        self.logs_dir = logs_dir
        self.session_id = session_id
        self.project_id = project_id
        self._setup_directories()

    def _setup_directories(self):
        """ログディレクトリを作成"""
        for subdir in ["orchestrator", "directors", "leaders", "workers", "tasks", "groups", "combined"]:
            (self.logs_dir / subdir).mkdir(parents=True, exist_ok=True)

    def log(
        self,
        level: str,
        message: str,
        agent_role: str,
        agent_type: str,
        agent_id: str,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        phase: Optional[int] = None,
        group: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, Any]] = None
    ):
        """構造化ログを出力"""
        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "session_id": self.session_id,
            "project_id": self.project_id,
            "agent": {
                "role": agent_role,
                "type": agent_type,
                "id": agent_id
            },
            "message": message,
        }

        if task_id:
            entry["task"] = {
                "id": task_id,
                "name": task_name,
                "phase": phase
            }

        if group:
            entry["group"] = group

        if details:
            entry["details"] = details

        if metrics:
            entry["metrics"] = metrics

        # 各ログファイルに出力
        self._write_to_files(entry)

    def _write_to_files(self, entry: dict):
        """複数のログファイルに出力"""
        json_line = json.dumps(entry, ensure_ascii=False)
        text_line = self._format_text(entry)

        # Agent別ログ
        agent_role = entry["agent"]["role"].lower()
        if agent_role == "orchestrator":
            self._append(f"orchestrator/orchestrator.log", text_line)
            self._append(f"orchestrator/orchestrator.jsonl", json_line)
        elif agent_role == "director":
            phase = entry.get("task", {}).get("phase", "unknown")
            self._append(f"directors/phase{phase}_director.log", text_line)
        elif agent_role == "leader":
            agent_type = entry["agent"]["type"]
            self._append(f"leaders/{agent_type}_leader.log", text_line)
        elif agent_role == "worker":
            agent_id = entry["agent"]["id"]
            self._append(f"workers/{agent_id}.log", text_line)

        # タスク別ログ
        if "task" in entry:
            task_id = entry["task"]["id"]
            self._append(f"tasks/{task_id}.log", text_line)
            self._append(f"tasks/{task_id}.jsonl", json_line)

        # グループ別ログ
        if "group" in entry:
            group = entry["group"].replace("/", "_")
            self._append(f"groups/{group}.log", text_line)

        # 全体ログ
        self._append("combined/all.log", text_line)
        self._append("combined/all.jsonl", json_line)

    def _append(self, path: str, line: str):
        """ファイルに追記"""
        full_path = self.logs_dir / path
        with open(full_path, "a") as f:
            f.write(line + "\n")

    def _format_text(self, entry: dict) -> str:
        """人間可読形式にフォーマット"""
        ts = entry["timestamp"][:23].replace("T", " ")
        level = entry["level"]
        agent = entry["agent"]
        agent_str = f"{agent['role']}:{agent['type']}:{agent['id']}"
        task_str = f"[{entry['task']['id']}]" if "task" in entry else ""

        line = f"{ts} [{level}] [{agent_str}] {task_str}\n  {entry['message']}"

        if "details" in entry:
            for key, value in entry["details"].items():
                line += f"\n  {key}: {value}"

        if "metrics" in entry:
            metrics = entry["metrics"]
            line += f"\n  duration: {metrics.get('duration_ms', 0)/1000:.1f}s"
            line += f", tokens: {metrics.get('tokens_used', 0)}"
            line += f", cost: ${metrics.get('cost_usd', 0):.4f}"

        return line
```

## ログ検索・閲覧

### ログクエリAPI

```python
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

@dataclass
class LogQuery:
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    levels: Optional[List[str]] = None
    agent_roles: Optional[List[str]] = None
    agent_types: Optional[List[str]] = None
    task_ids: Optional[List[str]] = None
    groups: Optional[List[str]] = None
    search_text: Optional[str] = None
    limit: int = 100
    offset: int = 0

class LogSearcher:
    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir

    def search(self, query: LogQuery) -> List[dict]:
        """ログを検索"""
        results = []

        # combined/all.jsonl を読み込み
        jsonl_path = self.logs_dir / "combined" / "all.jsonl"

        with open(jsonl_path) as f:
            for line in f:
                entry = json.loads(line)

                if self._matches(entry, query):
                    results.append(entry)

                    if len(results) >= query.offset + query.limit:
                        break

        return results[query.offset:query.offset + query.limit]

    def _matches(self, entry: dict, query: LogQuery) -> bool:
        """クエリにマッチするか判定"""
        # 時間範囲
        if query.start_time:
            entry_time = datetime.fromisoformat(entry["timestamp"].rstrip("Z"))
            if entry_time < query.start_time:
                return False

        if query.end_time:
            entry_time = datetime.fromisoformat(entry["timestamp"].rstrip("Z"))
            if entry_time > query.end_time:
                return False

        # レベル
        if query.levels and entry["level"] not in query.levels:
            return False

        # Agent
        if query.agent_roles and entry["agent"]["role"] not in query.agent_roles:
            return False

        if query.agent_types and entry["agent"]["type"] not in query.agent_types:
            return False

        # タスク
        if query.task_ids:
            if "task" not in entry or entry["task"]["id"] not in query.task_ids:
                return False

        # グループ
        if query.groups:
            if "group" not in entry or entry["group"] not in query.groups:
                return False

        # テキスト検索
        if query.search_text:
            if query.search_text.lower() not in entry["message"].lower():
                return False

        return True
```

## WebUI表示

### ログビューア機能

| 機能 | 説明 |
|------|------|
| フィルタ | Agent種別、グループ、タスクID、時間範囲、レベル |
| 検索 | テキスト検索 |
| リアルタイム | WebSocket経由でリアルタイム更新 |
| エクスポート | JSON/CSV形式でダウンロード |

### UIコンポーネント

```typescript
interface LogViewerProps {
  projectId: string;
  sessionId: string;
}

interface LogFilter {
  levels: string[];
  agentRoles: string[];
  agentTypes: string[];
  taskIds: string[];
  groups: string[];
  searchText: string;
  startTime: Date | null;
  endTime: Date | null;
}

interface LogEntry {
  timestamp: string;
  level: string;
  agent: {
    role: string;
    type: string;
    id: string;
  };
  task?: {
    id: string;
    name: string;
    phase: number;
  };
  group?: string;
  message: string;
  details?: Record<string, any>;
  metrics?: {
    tokens_used: number;
    duration_ms: number;
    cost_usd: number;
  };
}
```

### APIエンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | /logs | ログ検索 |
| GET | /logs/stream | リアルタイムストリーム（WebSocket） |
| GET | /logs/export | エクスポート |
| GET | /logs/stats | 統計情報 |

### クエリパラメータ例

```
GET /logs?levels=ERROR,WARN&agent_roles=WORKER&task_ids=task_p2_code_003&limit=50
```

## ログローテーション

### 設定

```yaml
# config/logging.yaml

logging:
  rotation:
    max_size_mb: 100
    max_files: 10
    compress: true

  retention:
    days: 30

  levels:
    default: INFO
    orchestrator: DEBUG
    worker: INFO
```

### 実装

```python
import gzip
from pathlib import Path

class LogRotator:
    def __init__(self, max_size_mb: int, max_files: int):
        self.max_size = max_size_mb * 1024 * 1024
        self.max_files = max_files

    def rotate_if_needed(self, log_path: Path):
        """必要に応じてローテーション"""
        if not log_path.exists():
            return

        if log_path.stat().st_size < self.max_size:
            return

        # ローテーション実行
        self._rotate(log_path)

    def _rotate(self, log_path: Path):
        """ログファイルをローテーション"""
        # 既存のローテーションファイルを番号上げ
        for i in range(self.max_files - 1, 0, -1):
            old = log_path.with_suffix(f".{i}.gz")
            new = log_path.with_suffix(f".{i + 1}.gz")
            if old.exists():
                if i + 1 >= self.max_files:
                    old.unlink()
                else:
                    old.rename(new)

        # 現在のログを圧縮
        with open(log_path, "rb") as f_in:
            with gzip.open(log_path.with_suffix(".1.gz"), "wb") as f_out:
                f_out.writelines(f_in)

        # 現在のログをクリア
        log_path.write_text("")
```
