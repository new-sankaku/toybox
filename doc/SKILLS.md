# スキル一覧

## カテゴリ

| カテゴリ | 説明 |
|---------|------|
| FILE | ファイル操作 |
| EXECUTE | コマンド実行 |
| PROJECT | プロジェクト解析 |
| ASSET | アセット生成・検査 |
| BUILD | ビルド・テスト |
| KNOWLEDGE | 知識・メモリ管理 |
| ORCHESTRATION | エージェント制御 |

## スキル一覧（全29スキル）

### FILE カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `file_read` | ファイルの内容を読み取る | `file_skills.py` |
| `file_write` | ファイルに内容を書き込む | `file_skills.py` |
| `file_edit` | ファイルの部分編集（文字列置換） | `file_skills.py` |
| `file_list` | ディレクトリ一覧表示 | `file_skills.py` |
| `file_delete` | ファイル・ディレクトリ削除 | `file_skills.py` |
| `code_search` | コード内テキスト検索 | `search_skills.py` |
| `file_search` | ファイル名検索 | `search_skills.py` |
| `web_fetch` | Web/APIデータ取得 | `web_skills.py` |
| `file_metadata` | ファイルメタデータ管理 | `cache_skills.py` |
| `diff_patch` | テキスト差分生成・適用 | `validation_skills.py` |

### EXECUTE カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `bash_execute` | Bashコマンド実行 | `bash_skill.py` |
| `python_execute` | Pythonコード実行 | `python_skill.py` |
| `git_operation` | Git操作（status/diff/log/blame/commit） | `git_skills.py` |

### PROJECT カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `project_analyze` | プロジェクト構造解析 | `project_skill.py` |
| `dependency_graph` | 依存関係グラフ解析 | `analysis_skills.py` |
| `schema_validate` | JSON/YAMLスキーマバリデーション | `validation_skills.py` |
| `game_data_transform` | ゲームデータフォーマット変換 | `game_skills.py` |
| `task_progress` | タスク進捗報告 | `progress_skills.py` |

### ASSET カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `image_generate` | 画像生成（ComfyUI） | `asset_skills.py` |
| `bgm_generate` | BGM生成 | `asset_skills.py` |
| `sfx_generate` | 効果音生成 | `asset_skills.py` |
| `voice_generate` | 音声生成（TTS） | `asset_skills.py` |
| `asset_inspect` | アセットメタデータ検査 | `asset_inspect_skill.py` |
| `sprite_sheet` | スプライトシート操作 | `game_skills.py` |

### BUILD カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `code_build` | プロジェクトビルド | `build_skills.py` |
| `code_test` | テスト実行 | `build_skills.py` |
| `code_lint` | リンター実行 | `build_skills.py` |

### KNOWLEDGE カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `agent_memory` | エージェント実行中のKVメモリ | `knowledge_skills.py` |
| `agent_output_query` | 他エージェント出力参照（read-only） | `knowledge_skills.py` |

### ORCHESTRATION カテゴリ
| スキル名 | 説明 | ファイル |
|---------|------|---------|
| `spawn_worker` | ワーカーエージェント生成・実行 | `orchestration_skills.py` |

## アーキテクチャ

### サービス注入
`agent_output_query` と `spawn_worker` はDataStoreやAgentExecutionServiceへの参照が必要なため、
`register_service_skills()` 関数を通じて遅延登録されます。

```
AgentExecutionService.__init__
  └─ _register_service_skills()
       └─ register_service_skills(registry, data_store, execution_service, sio)
            ├─ AgentOutputQuerySkill(data_store)
            └─ SpawnWorkerSkill(data_store, execution_service, sio)
```

### agent_memory のスコープ
- クラスレベル辞書 `{(project_id, agent_id): {key: {value, tags}}}` で保持
- `threading.Lock` でスレッドセーフ
- エージェント実行ごとに `(project_id, agent_id)` で自然にスコープされる

### task_progress のコールバック
- `SkillContext.on_progress: Optional[Callable[[int, str], None]]`
- `SkillExecutor` が `AgentContext.on_progress` を `SkillContext` に橋渡し
- `create_skill_executor()` の `on_progress` 引数で指定

### git_operation のセキュリティ
- `push`, `force-push`, `reset --hard`, `clean -f`, `checkout .` はブロック
- `asyncio.create_subprocess_exec` で安全に実行
- skills.yaml の `blocked_commands` でカスタマイズ可能

### dependency_graph の解析対象
- Python: `import` / `from ... import` 文
- JavaScript/TypeScript: `import ... from` / `require()` 文
- `node_modules`, `.git`, `__pycache__` 等は除外

## エージェント別スキルマッピング

全エージェント共通: `task_progress`, `agent_memory`

全リーダー共通: + `agent_output_query`, `spawn_worker`

| エージェント | 追加スキル |
|------------|-----------|
| `code_worker` | `dependency_graph`, `git_operation`, `diff_patch`, `schema_validate` |
| `code_leader` | `dependency_graph`, `git_operation`, `diff_patch` |
| `code_review_worker` | `dependency_graph`, `git_operation`, `diff_patch` |
| `build_worker` | `git_operation`, `schema_validate` |
| `architecture_leader` | `dependency_graph`, `schema_validate` |
| `asset_worker` | `asset_inspect`, `sprite_sheet` |
| `asset_leader` | `asset_inspect` |
| `integrator_leader` | `schema_validate` |
| `scenario_leader` | `game_data_transform` |
| `world_leader` | `game_data_transform` |
| `design_leader` | `game_data_transform` |
