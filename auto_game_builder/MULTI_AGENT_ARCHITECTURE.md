# LangGraph ベース マルチエージェント アーキテクチャ

## 1. 設計思想の修正

### 問題点（前回の設計）

```
❌ 全Agentがフラットに並んでいた
❌ シナリオの重要性が反映されていなかった
❌ 「シナリオがないと何も作れない」という現実を無視していた
```

### 新しい考え方

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│   シナリオが全ての基盤。他のAgentはシナリオに従属する。              │
│                                                                    │
│   - シナリオが「何を作るか」を決める                                 │
│   - キャラ/背景/音声はシナリオの指示で動く                          │
│   - 並列化できるのはシナリオの各パートが確定した後                   │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 階層構造

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             階層構造                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Level 0: 統括                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      Director Agent                                  │  │
│   │                 (全体統括・人間との窓口)                               │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│   Level 1: 中核 (シナリオが全てを支配)                                       │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                      Scenario Agent                                  │  │
│   │              (プロット → シーン → ダイアログ)                          │  │
│   │                                                                      │  │
│   │   このAgentが「何を作るか」を全て決定する                              │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│            ┌───────────────────────┼───────────────────────┐               │
│            │                       │                       │               │
│            ▼                       ▼                       ▼               │
│   Level 2: 実行 (シナリオの指示に従う)                                       │
│   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐         │
│   │  Character  │         │    Visual   │         │    Audio    │         │
│   │   Agent     │         │    Agent    │         │    Agent    │         │
│   │             │         │             │         │             │         │
│   │ ・キャラ設定 │         │ ・背景画像   │         │ ・BGM       │         │
│   │ ・立ち絵    │         │ ・UI        │         │ ・SE        │         │
│   │ ・表情差分  │         │ ・エフェクト │         │ ・ボイス    │         │
│   └─────────────┘         └─────────────┘         └─────────────┘         │
│                                    │                                        │
│                                    ▼                                        │
│   Level 3: 統合                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                       Code / Build Agent                             │  │
│   │                    (ゲームとして組み立てる)                            │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. シナリオ駆動フロー

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        シナリオ駆動フロー                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   Scenario Agentが段階的に情報を出力し、他Agentがそれに反応する              │
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                                                                     │  │
│   │   [Scenario Agent]                                                  │  │
│   │        │                                                            │  │
│   │        ├─── (1) 世界観・設定 ──────────────────────┐                │  │
│   │        │         │                                │                │  │
│   │        │         ▼                                ▼                │  │
│   │        │    [Character Agent]              [Audio Agent]           │  │
│   │        │     世界観に合うキャラ設定           世界観に合うBGMの方向性 │  │
│   │        │                                                            │  │
│   │        ├─── (2) プロット・章構成 ─────────────────┐                │  │
│   │        │         │                                │                │  │
│   │        │         ▼                                ▼                │  │
│   │        │    [Character Agent]              [Visual Agent]          │  │
│   │        │     登場キャラの立ち絵               各章の背景リスト       │  │
│   │        │                                                            │  │
│   │        ├─── (3) シーン詳細 ───────────────────────┐                │  │
│   │        │         │                                │                │  │
│   │        │         ▼                                ▼                │  │
│   │        │    [Visual Agent]                 [Audio Agent]           │  │
│   │        │     シーン別背景生成                シーン別BGM生成        │  │
│   │        │                                                            │  │
│   │        └─── (4) ダイアログ ───────────────────────┐                │  │
│   │                  │                  │             │                │  │
│   │                  ▼                  ▼             ▼                │  │
│   │           [Character Agent] [Audio Agent]  [Code Agent]            │  │
│   │            表情差分生成      ボイス生成     イベントスクリプト      │  │
│   │                                                                     │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. LangGraph 実装

### 4.1 なぜLangGraphか

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LangGraph の利点                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   1. 状態管理が組み込み                                                     │
│      - 各ノードが共有状態にアクセス                                         │
│      - 状態の変更履歴を追跡                                                 │
│                                                                             │
│   2. 条件分岐・並列実行が宣言的                                             │
│      - グラフとして視覚化しやすい                                           │
│      - 複雑なフローも明確に記述                                             │
│                                                                             │
│   3. 人間介入ポイントを簡単に設定                                           │
│      - interrupt_before / interrupt_after                                  │
│      - 承認待ちを自然に組み込める                                           │
│                                                                             │
│   4. チェックポイント・再開                                                 │
│      - 途中状態を保存                                                       │
│      - エラー後に再開可能                                                   │
│                                                                             │
│   5. LangChainエコシステムとの統合                                          │
│      - LLM、ツール、メモリとシームレスに連携                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 グラフ構造

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated

# 共有状態の定義
class GameState(TypedDict):
    # 企画
    project_config: dict

    # シナリオ関連
    world_settings: dict          # 世界観設定
    plot: dict                    # プロット
    scenes: list[dict]            # シーン一覧
    dialogs: list[dict]           # ダイアログ一覧

    # キャラクター関連
    characters: dict[str, dict]   # キャラ設定
    character_images: dict[str, str]  # キャラ画像パス

    # ビジュアル関連
    backgrounds: dict[str, str]   # 背景画像パス
    ui_assets: dict[str, str]     # UI素材パス

    # オーディオ関連
    bgm: dict[str, str]           # BGMパス
    se: dict[str, str]            # SEパス
    voices: dict[str, str]        # ボイスパス

    # メタ
    current_phase: str
    errors: list[str]
    human_feedback: list[dict]


# グラフ構築
def build_game_graph():
    graph = StateGraph(GameState)

    # ノード追加
    graph.add_node("scenario_world", scenario_world_node)
    graph.add_node("scenario_plot", scenario_plot_node)
    graph.add_node("scenario_scenes", scenario_scenes_node)
    graph.add_node("scenario_dialogs", scenario_dialogs_node)

    graph.add_node("character_settings", character_settings_node)
    graph.add_node("character_images", character_images_node)
    graph.add_node("character_expressions", character_expressions_node)

    graph.add_node("visual_backgrounds", visual_backgrounds_node)
    graph.add_node("visual_ui", visual_ui_node)

    graph.add_node("audio_bgm", audio_bgm_node)
    graph.add_node("audio_se", audio_se_node)
    graph.add_node("audio_voice", audio_voice_node)

    graph.add_node("build", build_node)
    graph.add_node("human_review", human_review_node)

    # エッジ定義（フロー）
    graph.set_entry_point("scenario_world")

    # 世界観 → 並列で(キャラ設定, プロット, BGM方向性)
    graph.add_edge("scenario_world", "scenario_plot")
    graph.add_edge("scenario_world", "character_settings")
    graph.add_edge("scenario_world", "audio_bgm")

    # プロット → 並列で(シーン詳細, 立ち絵生成)
    graph.add_edge("scenario_plot", "scenario_scenes")
    graph.add_edge("character_settings", "character_images")

    # シーン詳細 → 並列で(背景, SE)
    graph.add_edge("scenario_scenes", "visual_backgrounds")
    graph.add_edge("scenario_scenes", "audio_se")
    graph.add_edge("scenario_scenes", "scenario_dialogs")

    # ダイアログ → 並列で(表情差分, ボイス)
    graph.add_edge("scenario_dialogs", "character_expressions")
    graph.add_edge("scenario_dialogs", "audio_voice")

    # 全て完了 → ビルド
    graph.add_edge("character_expressions", "build")
    graph.add_edge("visual_backgrounds", "build")
    graph.add_edge("audio_voice", "build")
    graph.add_edge("audio_bgm", "build")
    graph.add_edge("audio_se", "build")

    # ビルド → 人間レビュー
    graph.add_edge("build", "human_review")

    # 人間レビュー → 終了 or 修正ループ
    graph.add_conditional_edges(
        "human_review",
        review_router,
        {
            "approved": END,
            "needs_fix_scenario": "scenario_dialogs",
            "needs_fix_visual": "visual_backgrounds",
            "needs_fix_audio": "audio_voice",
        }
    )

    return graph.compile()
```

### 4.3 ノード実装例

```python
# シナリオ: 世界観生成
async def scenario_world_node(state: GameState) -> GameState:
    """世界観・基本設定を生成"""
    llm = ChatOllama(model="llama3.1")

    prompt = f"""
    以下のゲーム企画に基づいて、世界観設定を作成してください。

    企画: {state['project_config']}

    出力形式 (JSON):
    {{
        "world_name": "世界の名前",
        "era": "時代設定",
        "tone": "作品のトーン (明るい/暗い/シリアス等)",
        "visual_style": "ビジュアルスタイル",
        "key_locations": ["場所1", "場所2"],
        "factions": ["勢力1", "勢力2"],
        "magic_system": "魔法/技術体系の説明",
        "themes": ["テーマ1", "テーマ2"]
    }}
    """

    response = await llm.ainvoke(prompt)
    world_settings = parse_json(response.content)

    return {
        **state,
        "world_settings": world_settings,
        "current_phase": "world_complete"
    }


# シナリオ: プロット生成
async def scenario_plot_node(state: GameState) -> GameState:
    """プロット・章構成を生成"""
    llm = ChatOllama(model="llama3.1")

    prompt = f"""
    世界観設定に基づいて、ゲームのプロットを作成してください。

    世界観: {state['world_settings']}

    出力形式 (JSON):
    {{
        "synopsis": "あらすじ",
        "chapters": [
            {{
                "chapter_num": 1,
                "title": "章タイトル",
                "summary": "概要",
                "locations": ["場所"],
                "characters_involved": ["キャラID"],
                "mood": "雰囲気"
            }}
        ],
        "ending_type": "エンディングの種類"
    }}
    """

    response = await llm.ainvoke(prompt)
    plot = parse_json(response.content)

    return {
        **state,
        "plot": plot,
        "current_phase": "plot_complete"
    }


# シナリオ: ダイアログ生成
async def scenario_dialogs_node(state: GameState) -> GameState:
    """各シーンのダイアログを生成"""
    llm = ChatOllama(model="llama3.1")
    dialogs = []

    for scene in state['scenes']:
        # キャラ情報を参照してダイアログ生成
        involved_chars = {
            char_id: state['characters'][char_id]
            for char_id in scene['characters_involved']
            if char_id in state['characters']
        }

        prompt = f"""
        以下のシーンのダイアログを作成してください。

        シーン: {scene}
        登場キャラクター: {involved_chars}

        各キャラクターの性格・口調を反映してください。

        出力形式 (JSON):
        {{
            "scene_id": "{scene['id']}",
            "lines": [
                {{
                    "speaker": "キャラID",
                    "text": "台詞",
                    "expression": "表情 (normal/happy/sad/angry/surprised)",
                    "voice_tone": "声のトーン指示"
                }}
            ]
        }}
        """

        response = await llm.ainvoke(prompt)
        dialog = parse_json(response.content)
        dialogs.append(dialog)

    return {
        **state,
        "dialogs": dialogs,
        "current_phase": "dialogs_complete"
    }


# キャラクター: 表情差分生成
async def character_expressions_node(state: GameState) -> GameState:
    """ダイアログで使われる表情の差分を生成"""
    comfyui = ComfyUIClient()

    # ダイアログから必要な表情を抽出
    required_expressions = set()
    for dialog in state['dialogs']:
        for line in dialog['lines']:
            char_id = line['speaker']
            expression = line['expression']
            required_expressions.add((char_id, expression))

    # 各表情を生成
    expression_images = {}
    for char_id, expression in required_expressions:
        if expression == "normal":
            continue  # 通常は立ち絵で生成済み

        char = state['characters'][char_id]
        base_image = state['character_images'].get(f"{char_id}_normal")

        image_path = await comfyui.generate(
            workflow="expression_variation",
            params={
                "base_image": base_image,
                "character_description": char['visual_description'],
                "expression": expression
            }
        )
        expression_images[f"{char_id}_{expression}"] = image_path

    return {
        **state,
        "character_images": {**state['character_images'], **expression_images},
        "current_phase": "expressions_complete"
    }


# ボイス生成
async def audio_voice_node(state: GameState) -> GameState:
    """ダイアログからボイスを生成"""
    voicevox = VOICEVOXClient()
    voices = {}

    # キャラIDとVOICEVOX話者IDのマッピング
    speaker_mapping = {
        char_id: char['voice_speaker_id']
        for char_id, char in state['characters'].items()
    }

    for dialog in state['dialogs']:
        for i, line in enumerate(dialog['lines']):
            char_id = line['speaker']
            text = line['text']
            speaker_id = speaker_mapping.get(char_id, 1)

            voice_path = await voicevox.generate(
                text=text,
                speaker_id=speaker_id
            )

            voice_id = f"{dialog['scene_id']}_{i:04d}"
            voices[voice_id] = voice_path

    return {
        **state,
        "voices": voices,
        "current_phase": "voices_complete"
    }
```

---

## 5. 並列実行の実現

### 5.1 LangGraphの並列ノード

```python
from langgraph.graph import StateGraph

graph = StateGraph(GameState)

# 並列実行したいノードは、同じ親から分岐させる
#
#                 scenario_world
#                      │
#          ┌──────────┼──────────┐
#          ▼          ▼          ▼
#    char_settings  plot      audio_bgm  ← これらは並列実行される
#

graph.add_edge("scenario_world", "character_settings")
graph.add_edge("scenario_world", "scenario_plot")
graph.add_edge("scenario_world", "audio_bgm")

# LangGraphは同じ親から出るエッジを自動的に並列実行する
```

### 5.2 並列実行の可視化

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LangGraph 実行フロー                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   START                                                                     │
│     │                                                                       │
│     ▼                                                                       │
│   ┌─────────────────┐                                                      │
│   │ scenario_world  │  ← シーケンシャル (最初に実行)                        │
│   └────────┬────────┘                                                      │
│            │                                                                │
│   ─────────┼──────────────────────────────────  並列開始                   │
│            │                                                                │
│   ┌────────┴────────┬─────────────────┬─────────────────┐                  │
│   ▼                 ▼                 ▼                 ▼                  │
│ ┌───────────┐  ┌───────────┐   ┌───────────┐    ┌───────────┐             │
│ │ char_     │  │ scenario_ │   │ audio_bgm │    │ audio_se  │             │
│ │ settings  │  │ plot      │   │           │    │           │             │
│ └─────┬─────┘  └─────┬─────┘   └───────────┘    └───────────┘             │
│       │              │                                                      │
│   ────┼──────────────┼─────────────────────────  同期ポイント              │
│       │              │                                                      │
│       ▼              ▼                                                      │
│ ┌───────────┐  ┌───────────┐                                               │
│ │ char_     │  │ scenario_ │   ← これらも並列                              │
│ │ images    │  │ scenes    │                                               │
│ └─────┬─────┘  └─────┬─────┘                                               │
│       │              │                                                      │
│       │              ▼                                                      │
│       │        ┌───────────┐                                               │
│       │        │ scenario_ │                                               │
│       │        │ dialogs   │                                               │
│       │        └─────┬─────┘                                               │
│       │              │                                                      │
│   ────┼──────────────┼─────────────────────────  並列開始                  │
│       │              │                                                      │
│   ┌───┴───┐    ┌─────┴─────┬─────────────┐                                │
│   ▼       ▼    ▼           ▼             ▼                                │
│ ┌─────┐ ┌─────┐ ┌───────┐ ┌───────┐ ┌───────────┐                        │
│ │expr │ │back │ │voice  │ │ UI    │ │backgrounds│                        │
│ │     │ │     │ │       │ │       │ │           │                        │
│ └──┬──┘ └──┬──┘ └───┬───┘ └───┬───┘ └─────┬─────┘                        │
│    │       │        │         │           │                               │
│    └───────┴────────┴─────────┴───────────┘                               │
│                        │                                                    │
│   ─────────────────────┼───────────────────────  同期ポイント              │
│                        │                                                    │
│                        ▼                                                    │
│                  ┌───────────┐                                             │
│                  │   build   │  ← 全て揃ったらビルド                       │
│                  └─────┬─────┘                                             │
│                        │                                                    │
│                        ▼                                                    │
│                  ┌───────────┐                                             │
│                  │  human_   │  ← 人間レビュー（interrupt point）          │
│                  │  review   │                                             │
│                  └─────┬─────┘                                             │
│                        │                                                    │
│              ┌─────────┼─────────┐                                         │
│              ▼         ▼         ▼                                         │
│           [END]   [fix_loop]  [fix_loop]                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 人間介入ポイント

### 6.1 interrupt設定

```python
# 人間の承認が必要なポイントを設定
graph = build_game_graph()

# チェックポイント設定（状態保存）
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("game_state.db")

app = graph.compile(
    checkpointer=checkpointer,
    interrupt_before=["human_review"],  # ここで一時停止
)

# 実行
async def run_with_human_review():
    config = {"configurable": {"thread_id": "game_001"}}

    # 人間レビューまで実行
    result = await app.ainvoke(initial_state, config)

    # 人間レビュー待ち
    print("レビュー待ち状態です")
    print("_outbox/pending_review/ を確認してください")

    # 人間がフィードバックを入力後、続行
    feedback = load_human_feedback()  # _inbox/feedback/ から読み込み

    # フィードバックを状態に追加して続行
    result = await app.ainvoke(
        {"human_feedback": feedback},
        config
    )
```

### 6.2 フィードバック処理

```python
def review_router(state: GameState) -> str:
    """人間レビュー後の分岐を決定"""
    feedback = state.get("human_feedback", [])

    if not feedback:
        return "approved"

    # フィードバックの種類で分岐
    for fb in feedback:
        if fb["type"] == "scenario_fix":
            return "needs_fix_scenario"
        elif fb["type"] == "visual_fix":
            return "needs_fix_visual"
        elif fb["type"] == "audio_fix":
            return "needs_fix_audio"

    return "approved"
```

---

## 7. システム全体構成

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                         │
│                         LangGraph ベース ゲーム生成システム                               │
│                                                                                         │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│    ┌─────────────┐          ┌─────────────────────────────────────────────────────┐   │
│    │   Human     │◄────────►│              _inbox / _outbox                        │   │
│    └─────────────┘          │         (フォルダベースI/F)                           │   │
│                             └───────────────────────┬─────────────────────────────┘   │
│                                                     │                                  │
│                                                     ▼                                  │
│    ┌───────────────────────────────────────────────────────────────────────────────┐  │
│    │                            LangGraph Engine                                    │  │
│    │                                                                                │  │
│    │   ┌─────────────────────────────────────────────────────────────────────────┐ │  │
│    │   │                         State (GameState)                                │ │  │
│    │   │   - project_config, world_settings, plot, scenes, dialogs               │ │  │
│    │   │   - characters, character_images                                        │ │  │
│    │   │   - backgrounds, bgm, se, voices                                        │ │  │
│    │   │   - human_feedback, errors                                              │ │  │
│    │   └─────────────────────────────────────────────────────────────────────────┘ │  │
│    │                                      │                                        │  │
│    │   ┌──────────────────────────────────┴────────────────────────────────────┐  │  │
│    │   │                              Nodes                                     │  │  │
│    │   │                                                                        │  │  │
│    │   │   ┌─────────────┐                                                     │  │  │
│    │   │   │  Scenario   │  scenario_world → scenario_plot → scenario_scenes   │  │  │
│    │   │   │   Nodes     │                              → scenario_dialogs     │  │  │
│    │   │   └─────────────┘                                                     │  │  │
│    │   │                                                                        │  │  │
│    │   │   ┌─────────────┐                                                     │  │  │
│    │   │   │  Character  │  character_settings → character_images              │  │  │
│    │   │   │   Nodes     │                    → character_expressions          │  │  │
│    │   │   └─────────────┘                                                     │  │  │
│    │   │                                                                        │  │  │
│    │   │   ┌─────────────┐                                                     │  │  │
│    │   │   │   Visual    │  visual_backgrounds, visual_ui, visual_effects      │  │  │
│    │   │   │   Nodes     │                                                     │  │  │
│    │   │   └─────────────┘                                                     │  │  │
│    │   │                                                                        │  │  │
│    │   │   ┌─────────────┐                                                     │  │  │
│    │   │   │   Audio     │  audio_bgm, audio_se, audio_voice                   │  │  │
│    │   │   │   Nodes     │                                                     │  │  │
│    │   │   └─────────────┘                                                     │  │  │
│    │   │                                                                        │  │  │
│    │   │   ┌─────────────┐                                                     │  │  │
│    │   │   │   Build     │  build, human_review                                │  │  │
│    │   │   │   Nodes     │                                                     │  │  │
│    │   │   └─────────────┘                                                     │  │  │
│    │   │                                                                        │  │  │
│    │   └────────────────────────────────────────────────────────────────────────┘  │  │
│    │                                                                                │  │
│    │   ┌─────────────────────────────────────────────────────────────────────────┐ │  │
│    │   │                         Checkpointer (SQLite)                           │ │  │
│    │   │                      状態保存・再開・履歴管理                             │ │  │
│    │   └─────────────────────────────────────────────────────────────────────────┘ │  │
│    │                                                                                │  │
│    └────────────────────────────────────────────────────────────────────────────────┘  │
│                                          │                                             │
│                    ┌─────────────────────┼─────────────────────┐                      │
│                    │                     │                     │                      │
│                    ▼                     ▼                     ▼                      │
│             ┌───────────┐         ┌───────────┐         ┌───────────┐                │
│             │  Ollama   │         │  ComfyUI  │         │ VOICEVOX  │                │
│             │  (LLM)    │         │  (Image)  │         │  (Voice)  │                │
│             └───────────┘         └───────────┘         └───────────┘                │
│                                                                                         │
│                                          │                                             │
│                                          ▼                                             │
│             ┌───────────────────────────────────────────────────────────────────┐     │
│             │                        Assets Storage                              │     │
│             │   assets/generated/  assets/approved/  assets/mock/               │     │
│             └───────────────────────────────────────────────────────────────────┘     │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. 依存関係まとめ

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   シナリオ中心の依存関係                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   scenario_world (世界観)                                                   │
│        │                                                                    │
│        ├──────► character_settings (キャラ設定)                             │
│        │              │                                                     │
│        │              └──────► character_images (立ち絵)                    │
│        │                                                                    │
│        ├──────► scenario_plot (プロット)                                    │
│        │              │                                                     │
│        │              └──────► scenario_scenes (シーン詳細)                 │
│        │                              │                                     │
│        │                              ├──────► visual_backgrounds (背景)   │
│        │                              │                                     │
│        │                              └──────► scenario_dialogs (台詞)     │
│        │                                              │                     │
│        │                                              ├──► char_expressions│
│        │                                              │                     │
│        │                                              └──► audio_voice     │
│        │                                                                    │
│        └──────► audio_bgm (BGM) ← 世界観の雰囲気から先行生成可能            │
│                                                                             │
│                                                                             │
│   【ポイント】                                                               │
│   - シナリオの各段階で、対応するアセット生成が解禁される                      │
│   - BGMだけは世界観から先行して生成開始できる                                │
│   - ダイアログが確定しないと表情差分・ボイスは作れない                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. 実装ファイル構成

```
auto_game_builder/
├── main.py                    # エントリーポイント
├── graph/
│   ├── __init__.py
│   ├── game_graph.py          # LangGraphグラフ定義
│   ├── state.py               # GameState定義
│   └── nodes/
│       ├── scenario.py        # シナリオ系ノード
│       ├── character.py       # キャラクター系ノード
│       ├── visual.py          # ビジュアル系ノード
│       ├── audio.py           # オーディオ系ノード
│       └── build.py           # ビルド系ノード
├── tools/
│   ├── ollama_client.py       # LLMクライアント
│   ├── comfyui_client.py      # 画像生成クライアント
│   ├── voicevox_client.py     # 音声合成クライアント
│   └── suno_client.py         # BGM生成クライアント
├── io/
│   ├── inbox_watcher.py       # _inbox監視
│   ├── outbox_writer.py       # _outbox出力
│   └── feedback_parser.py     # フィードバック解析
└── utils/
    ├── mock_generator.py      # モック生成
    └── asset_manager.py       # アセット管理
```

---

*作成日: 2026-01-14*
*バージョン: 2.0 (LangGraph + シナリオ中心設計)*
