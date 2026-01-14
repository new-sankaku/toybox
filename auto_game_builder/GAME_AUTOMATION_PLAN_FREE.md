# ゲーム開発完全自動化計画書 (無料版)

## コンセプト
**ComfyUI + ローカルAI を中心に、お金をかけずにゲーム開発を自動化する**

---

## 1. ツール構成

### メインツール (全て無料)

```
┌─────────────────────────────────────────────────────────┐
│                    ComfyUI (中核)                        │
│  ├─ 画像生成 (SDXL, Flux, SD3)                          │
│  ├─ 動画生成 (AnimateDiff, SVD)                         │
│  ├─ 3D生成 (TripoSR, Zero123++)                         │
│  └─ 音声生成 (AudioLDM, Bark)                           │
├─────────────────────────────────────────────────────────┤
│                   補助ツール                             │
│  ├─ VOICEVOX / COEIROINK (日本語音声)                   │
│  ├─ RVC (ボイスチェンジャー)                            │
│  ├─ Ollama (ローカルLLM)                                │
│  ├─ Whisper (音声認識)                                  │
│  └─ Blender + Python (3D後処理)                         │
└─────────────────────────────────────────────────────────┘
```

---

## 2. データ別 生成方法 (ComfyUI中心)

### 2.1 ビジュアルアセット

| データ種類 | ツール | ComfyUIノード/モデル | 備考 |
|-----------|--------|---------------------|------|
| **2Dキャラクター** | ComfyUI | SDXL, Flux, Pony系 | LoRAでスタイル統一 |
| **2D背景** | ComfyUI | SDXL + ControlNet | 高品質生成可能 |
| **UIアイコン** | ComfyUI | SDXL + IPAdapter | 参照画像で一貫性確保 |
| **スプライトシート** | ComfyUI | AnimateDiff + 後処理 | フレーム抽出必要 |
| **3Dモデル** | ComfyUI | TripoSR, Zero123++ | Blenderで後処理 |
| **3Dテクスチャ** | ComfyUI | SDXL (tiling) | シームレステクスチャ対応 |
| **エフェクト** | ComfyUI | AnimateDiff + Deforum | 短いループエフェクト |
| **ドット絵** | ComfyUI | Pixel Art LoRA | レトロゲーム向け |

### 2.2 オーディオアセット

| データ種類 | ツール | 詳細 | 備考 |
|-----------|--------|------|------|
| **BGM** | ComfyUI + Suno無料枠 | AudioLDM, MusicGen | ローカル品質は中程度 |
| **効果音(SE)** | ComfyUI | AudioLDM | テキストから効果音生成 |
| **ボイス(日本語)** | VOICEVOX | 無料・商用可 | 高品質、多キャラ |
| **ボイス(英語)** | Bark / Coqui TTS | ComfyUIノードあり | 感情表現可能 |
| **ボイスチェンジ** | RVC | 声質変換 | 自分の声をキャラ声に |

### 2.3 テキスト/シナリオ

| データ種類 | ツール | モデル | 備考 |
|-----------|--------|-------|------|
| **シナリオ** | Ollama | Llama3, Qwen2.5, Command-R | ローカル実行 |
| **ダイアログ** | Ollama | 同上 | 無制限生成 |
| **コード生成** | Ollama | Codellama, Qwen2.5-Coder | 中規模まで対応 |
| **翻訳** | Ollama | ALMA, Qwen | 品質は商用APIに劣る |

### 2.4 動画/アニメーション

| データ種類 | ツール | ComfyUIノード | 備考 |
|-----------|--------|--------------|------|
| **短いアニメ** | ComfyUI | AnimateDiff | 2-4秒ループ |
| **Image to Video** | ComfyUI | SVD (Stable Video Diffusion) | 静止画から動画化 |
| **フレーム補間** | ComfyUI | FILM, RIFE | フレームレート向上 |
| **カットシーン** | ComfyUI | SVD + AnimateDiff | 短尺のみ |

---

## 3. ComfyUI 必須カスタムノード

### インストール推奨ノード

```bash
# ComfyUI Manager (必須)
cd ComfyUI/custom_nodes
git clone https://github.com/ltdrdata/ComfyUI-Manager

# 画像生成強化
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus
git clone https://github.com/Fannovel16/comfyui_controlnet_aux
git clone https://github.com/ssitu/ComfyUI_UltimateSDUpscale

# アニメーション
git clone https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved
git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite

# 3D生成
git clone https://github.com/flowtyone/ComfyUI-Flowty-TripoSR

# 音声生成
git clone https://github.com/eigenpunk/ComfyUI-audio
git clone https://github.com/SaltAI/SaltAI_AudioViz

# LLM連携
git clone https://github.com/pythongosssss/ComfyUI-Custom-Scripts
```

### 推奨モデル

```
models/checkpoints/
├── sd_xl_base_1.0.safetensors      # SDXL base
├── flux1-dev.safetensors            # Flux (高品質)
├── animagineXL.safetensors          # アニメ向け
└── ponyDiffusionV6.safetensors      # Pony系

models/loras/
├── pixel-art-xl.safetensors         # ドット絵
├── anime-style.safetensors          # アニメ調
└── game-ui-icons.safetensors        # UIアイコン用

models/controlnet/
├── control_v11p_sd15_openpose       # ポーズ制御
├── control_v11f1e_sd15_tile         # タイル/アップスケール
└── control_v11p_sd15_canny          # エッジ検出
```

---

## 4. 無料代替ツール詳細

### 4.1 音声合成 (VOICEVOX)

```python
# VOICEVOX Engine API (ローカル)
import requests

def generate_voice(text, speaker_id=1):
    # 音声合成クエリ作成
    query = requests.post(
        f'http://localhost:50021/audio_query',
        params={'text': text, 'speaker': speaker_id}
    ).json()

    # 音声合成
    audio = requests.post(
        f'http://localhost:50021/synthesis',
        params={'speaker': speaker_id},
        json=query
    )
    return audio.content
```

**利用可能キャラクター (無料・商用可)**
- ずんだもん、四国めたん、春日部つむぎ、他多数

### 4.2 ローカルLLM (Ollama)

```bash
# インストール
curl -fsSL https://ollama.com/install.sh | sh

# モデルダウンロード
ollama pull llama3.1:8b        # 汎用 (8B)
ollama pull qwen2.5-coder:7b   # コード特化
ollama pull command-r:35b      # 高性能 (要VRAM)

# API利用
curl http://localhost:11434/api/generate -d '{
  "model": "llama3.1:8b",
  "prompt": "RPGゲームのシナリオを書いて"
}'
```

### 4.3 BGM生成 (無料枠活用)

| サービス | 無料枠 | 制限 |
|---------|-------|------|
| **Suno** | 50クレジット/日 | 10曲程度/日 |
| **Udio** | 100クレジット/月 | 25曲程度/月 |
| **MusicGen (ローカル)** | 無制限 | 品質は中程度 |

---

## 5. 推奨ワークフロー構成

```
[自動化パイプライン]

1. 企画フェーズ
   └─ Ollama (Llama3) → ゲーム企画書生成

2. アセット生成フェーズ
   ├─ ComfyUI → キャラクター画像生成
   │   ├─ SDXL/Flux + LoRA
   │   ├─ IPAdapter (一貫性維持)
   │   └─ ControlNet (ポーズ指定)
   │
   ├─ ComfyUI → 背景画像生成
   │   └─ SDXL + ControlNet Depth
   │
   ├─ ComfyUI → UI/アイコン生成
   │   └─ SDXL + IPAdapter
   │
   ├─ ComfyUI → 効果音生成
   │   └─ AudioLDM
   │
   ├─ VOICEVOX → ボイス生成
   │
   └─ Suno無料枠 → BGM生成

3. アニメーション生成
   └─ ComfyUI → AnimateDiff
       ├─ キャラアニメーション
       └─ エフェクトアニメーション

4. コード生成
   └─ Ollama (Qwen2.5-Coder) → ゲームロジック

5. 統合・ビルド
   └─ 手動 or CI/CD
```

---

## 6. 必要スペック

### 最低スペック
- GPU: RTX 3060 12GB (SDXL動作)
- RAM: 32GB
- VRAM: 12GB
- Storage: 100GB+ (モデル保存)

### 推奨スペック
- GPU: RTX 4070 12GB以上
- RAM: 64GB
- VRAM: 16GB+
- Storage: 500GB SSD

### 各機能のVRAM目安
| 機能 | 必要VRAM |
|-----|---------|
| SDXL画像生成 | 8-10GB |
| Flux画像生成 | 12-16GB |
| AnimateDiff | 10-12GB |
| TripoSR (3D) | 8GB |
| Ollama 8Bモデル | 6-8GB |
| VOICEVOX | 2GB |

---

## 7. コスト比較

### 有料API vs 無料ローカル

| 項目 | 有料API (月額目安) | ローカル (初期投資) |
|-----|-------------------|-------------------|
| 画像生成 | $50-200 | $0 (GPU所有時) |
| BGM生成 | $30-50 | $0 (品質中) |
| ボイス生成 | $50-100 | $0 (VOICEVOX) |
| LLM | $50-200 | $0 (Ollama) |
| **合計** | **$180-550/月** | **$0/月** |

### 初期投資 (PC未所有の場合)
- GPU (RTX 4070): ~$600
- ゲーミングPC一式: ~$1,500-2,000

**損益分岐点: 3-4ヶ月で元が取れる**

---

## 8. 制限事項と対策

### ComfyUIの限界

| 制限 | 対策 |
|-----|------|
| 長尺動画生成不可 | 短いクリップを連結 |
| BGM品質が中程度 | Suno/Udio無料枠を活用 |
| 3Dモデル品質 | Blenderで後処理 |
| LLM性能 | 重要な部分のみClaude無料枠 |

### 品質確保のコツ
1. **一貫性** → IPAdapterで参照画像を使う
2. **スタイル統一** → 専用LoRAを作成/使用
3. **アニメ品質** → AnimateDiffのMotion LoRA活用
4. **音声品質** → VOICEVOXの調声機能を活用

---

## 9. 次のアクション

1. [ ] ComfyUI環境構築
2. [ ] 必須カスタムノードのインストール
3. [ ] 推奨モデルのダウンロード
4. [ ] VOICEVOX/Ollamaのセットアップ
5. [ ] 各機能の動作確認ワークフロー作成
6. [ ] 自動化スクリプトの開発

---

*作成日: 2026-01-14*
*ポリシー: 完全無料でゲーム開発自動化を実現*
