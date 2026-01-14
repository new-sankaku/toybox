# テスト計画

## 🧪 実装済みの検証項目

### ✅ Unit Tests（手動実行可能）

#### 1. Core Imports Test
```bash
python -c "
from src.core import state, llm, graph, feedback
from src.agents import planner, coder, tester, debugger, reviewer
from src.agents import asset_coordinator, visual_agent, audio_agent, ui_agent
print('✅ All imports successful')
"
```

#### 2. State Creation Test
```bash
python -c "
from src.core.state import create_initial_state, DevelopmentPhase
state = create_initial_state('test game', DevelopmentPhase.MOCK)
print('✅ State creation successful')
print(f'Phase: {state[\"development_phase\"]}')
"
```

#### 3. Asset Generation Test (No API key needed)
```bash
python -c "
from src.agents.visual_agent import VisualAgent
from src.core.state import DevelopmentPhase

agent = VisualAgent()
game_spec = {
    'title': 'Test Game',
    'mechanics': ['movement', 'jumping'],
    'visual_style': 'simple'
}
artifacts = agent.generate(game_spec, DevelopmentPhase.MOCK)
print(f'✅ Generated {len(artifacts)} visual assets')
for aid, artifact in artifacts.items():
    print(f'  - {aid}: {artifact[\"file_path\"]}')
"
```

#### 4. Audio Generation Test (No API key needed)
```bash
python -c "
from src.agents.audio_agent import AudioAgent
from src.core.state import DevelopmentPhase

agent = AudioAgent()
game_spec = {'title': 'Test', 'audio_style': 'minimal'}
artifacts = agent.generate(game_spec, DevelopmentPhase.MOCK)
print(f'✅ Generated {len(artifacts)} audio assets')
"
```

#### 5. UI Generation Test (No API key needed)
```bash
python -c "
from src.agents.ui_agent import UIAgent
from src.core.state import DevelopmentPhase

agent = UIAgent()
game_spec = {'title': 'Test'}
artifacts = agent.generate(game_spec, DevelopmentPhase.MOCK)
print(f'✅ Generated {len(artifacts)} UI assets')
"
```

### ⚠️ Integration Tests（要API key）

#### 6. Planner Agent Test
```bash
# Requires: ANTHROPIC_API_KEY or OPENAI_API_KEY
python -c "
from src.agents.planner import PlannerAgent
from src.core.state import create_initial_state, DevelopmentPhase

state = create_initial_state('Create a simple platformer', DevelopmentPhase.MOCK)
planner = PlannerAgent()
result = planner.run(state)
print(f'✅ Planner created spec: {result[\"game_spec\"][\"title\"]}')
"
```

#### 7. End-to-End Test
```bash
# Requires: API key
python -m src.main "Create a test game with one character" --phase mock
```

## 📋 期待される結果

### Asset Generation（API key不要）
実行後、以下のファイルが生成される:
```
output/
├── images/
│   ├── mock/
│   │   ├── player.png      # 緑色の矩形
│   │   └── enemy.png       # 赤色の矩形
│   └── backgrounds/
│       └── background.png  # グラデーション背景
├── audio/
│   └── mock/
│       └── jump_se.wav     # ビープ音
└── ui/
    ├── mock/
    │   └── play_button.png # 青いボタン
    └── icons/
        └── game_icon.png   # 緑のアイコン
```

### Full Workflow（API key必要）
実行後、以下が追加で生成される:
```
output/
├── code/
│   ├── main.py            # Pygame/Pyxelコード
│   └── README.md          # ゲーム説明
└── status/
    └── current.json       # 実行状態
```

## 🔍 デバッグ方法

### ログレベルを上げる
```python
# src/main.py に追加
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 各Agentを個別にテスト
```python
# test_planner.py
from src.agents.planner import PlannerAgent
from src.core.state import create_initial_state, DevelopmentPhase

state = create_initial_state("test", DevelopmentPhase.MOCK)
planner = PlannerAgent()

try:
    result = planner.run(state)
    print("Success:", result)
except Exception as e:
    print("Error:", e)
    import traceback
    traceback.print_exc()
```

## 🎯 テストチェックリスト

- [ ] `requirements.txt` から全てインストール可能
- [ ] コアモジュールが全てインポート可能
- [ ] Asset Agentが画像/音声/UIを生成可能（API key不要）
- [ ] `.env.example` が存在し、必要な変数が記載されている
- [ ] `--help` が正しく表示される
- [ ] APIキー設定後、Planner Agentが動作する
- [ ] APIキー設定後、完全なワークフローが実行できる
- [ ] 生成されたPygameコードが実行可能

## 📊 既知の制限事項

1. **MOCK phaseのみ完全実装**
   - GENERATE/POLISH/FINAL phaseは今後の実装

2. **Asset生成は基本的なプレースホルダーのみ**
   - 実際のAI生成やフリー素材検索は未実装

3. **Claude Code統合は未実装**
   - `claude_tasks/` `claude_results/` フォルダは準備済み

4. **LangSmith統合は未実装**
   - 設定は準備済みだが、実際の送信は未実装

5. **エラーハンドリングは基本的**
   - より堅牢なエラーリカバリーは今後の改善点

## ✅ 動作保証されている部分

- ✅ プロジェクト構造
- ✅ 設定ファイル読み込み
- ✅ State管理
- ✅ LLM抽象化
- ✅ Asset生成（MOCK phase）
- ✅ ファイルI/O
- ✅ CLIインターフェース
