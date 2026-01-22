# 機械的作業戦略

## 概要

LLMを使用せずに機械的に実行できる作業はScriptで処理する。
画像の色調調整やファイルのフォーマット等、決定論的な処理はLLMよりScriptの方が高速・安価・確実。

## 判断基準

### LLM vs Script

| 作業種別 | LLM | Script | 理由 |
|---------|-----|--------|------|
| 画像リサイズ | x | o | パラメータ化可能 |
| 画像色調調整 | x | o | 決定論的処理 |
| 画像フォーマット変換 | x | o | 決定論的処理 |
| コードフォーマット | x | o | lint/prettier |
| ファイル一括置換 | x | o | sed/awk |
| テスト実行 | x | o | pytest/jest |
| ビルド実行 | x | o | npm/gradle |
| Gitコミット | x | o | コマンド実行 |
| デザイン生成 | o | x | 創造性が必要 |
| コード設計 | o | x | 判断が必要 |
| バグ修正 | o | x | 理解が必要 |
| レビュー | o | x | 判断が必要 |

### 判断フロー

```
タスクを受け取る
    │
    v
機械的に実行可能か？
    │
    ├── Yes → Script実行
    │
    └── No → LLMに依頼
```

## Scriptライブラリ

### フォルダ構造

```
scripts/
├── image/
│   ├── resize.py
│   ├── color_adjust.py
│   ├── format_convert.py
│   └── batch_process.py
│
├── code/
│   ├── format.sh
│   ├── lint.sh
│   ├── bulk_rename.py
│   └── dependency_update.py
│
├── test/
│   ├── run_tests.sh
│   ├── coverage_report.py
│   └── benchmark.py
│
├── build/
│   ├── build.sh
│   ├── package.py
│   └── deploy.sh
│
├── git/
│   ├── commit.sh
│   ├── merge.sh
│   └── branch_cleanup.py
│
└── util/
    ├── file_operations.py
    └── json_yaml_converter.py
```

### 主要Script

#### scripts/image/resize.py

```python
#!/usr/bin/env python3
"""画像リサイズスクリプト"""

import argparse
from PIL import Image
from pathlib import Path

def resize_image(input_path: str, output_path: str, width: int, height: int):
    """画像をリサイズ"""
    with Image.open(input_path) as img:
        resized = img.resize((width, height), Image.LANCZOS)
        resized.save(output_path)
    return output_path

def main():
    parser = argparse.ArgumentParser(description="画像リサイズ")
    parser.add_argument("input", help="入力ファイルパス")
    parser.add_argument("output", help="出力ファイルパス")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)

    args = parser.parse_args()
    result = resize_image(args.input, args.output, args.width, args.height)
    print(f"Resized: {result}")

if __name__ == "__main__":
    main()
```

#### scripts/image/color_adjust.py

```python
#!/usr/bin/env python3
"""画像色調調整スクリプト"""

import argparse
from PIL import Image, ImageEnhance

def adjust_color(
    input_path: str,
    output_path: str,
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0
):
    """色調を調整"""
    with Image.open(input_path) as img:
        # 明るさ
        if brightness != 1.0:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(brightness)

        # コントラスト
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(contrast)

        # 彩度
        if saturation != 1.0:
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(saturation)

        img.save(output_path)

    return output_path

def main():
    parser = argparse.ArgumentParser(description="画像色調調整")
    parser.add_argument("input", help="入力ファイルパス")
    parser.add_argument("output", help="出力ファイルパス")
    parser.add_argument("--brightness", type=float, default=1.0)
    parser.add_argument("--contrast", type=float, default=1.0)
    parser.add_argument("--saturation", type=float, default=1.0)

    args = parser.parse_args()
    result = adjust_color(
        args.input, args.output,
        args.brightness, args.contrast, args.saturation
    )
    print(f"Adjusted: {result}")

if __name__ == "__main__":
    main()
```

#### scripts/code/format.sh

```bash
#!/bin/bash
# コードフォーマットスクリプト

set -e

TARGET=${1:-.}

# Python
if command -v black &> /dev/null; then
    echo "Formatting Python files..."
    black "$TARGET" --quiet
fi

# JavaScript/TypeScript
if command -v prettier &> /dev/null; then
    echo "Formatting JS/TS files..."
    prettier --write "$TARGET/**/*.{js,ts,jsx,tsx}" --log-level error
fi

# C#
if command -v dotnet &> /dev/null; then
    echo "Formatting C# files..."
    dotnet format "$TARGET" --verbosity quiet
fi

echo "Formatting complete."
```

## WORKERからのScript呼び出し

### ScriptExecutor

```python
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class ScriptResult:
    success: bool
    output: str
    error: Optional[str]
    return_code: int

class ScriptExecutor:
    def __init__(self, scripts_dir: Path):
        self.scripts_dir = scripts_dir

    def execute(
        self,
        script_name: str,
        args: Dict[str, Any],
        timeout: int = 300
    ) -> ScriptResult:
        """Scriptを実行"""

        script_path = self._find_script(script_name)
        if not script_path:
            return ScriptResult(
                success=False,
                output="",
                error=f"Script not found: {script_name}",
                return_code=-1
            )

        # コマンドを構築
        cmd = self._build_command(script_path, args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return ScriptResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                return_code=result.returncode
            )

        except subprocess.TimeoutExpired:
            return ScriptResult(
                success=False,
                output="",
                error="Script timed out",
                return_code=-1
            )

    def _find_script(self, name: str) -> Optional[Path]:
        """Scriptを検索"""
        for ext in [".py", ".sh", ""]:
            # カテゴリ/名前 形式を試す
            parts = name.split("/")
            if len(parts) == 2:
                path = self.scripts_dir / parts[0] / (parts[1] + ext)
            else:
                path = self.scripts_dir / (name + ext)

            if path.exists():
                return path

        return None

    def _build_command(self, script_path: Path, args: Dict[str, Any]) -> list:
        """コマンドを構築"""
        cmd = []

        # インタプリタを決定
        if script_path.suffix == ".py":
            cmd.append("python3")
        elif script_path.suffix == ".sh":
            cmd.append("bash")

        cmd.append(str(script_path))

        # 引数を追加
        for key, value in args.items():
            if isinstance(value, bool):
                if value:
                    cmd.append(f"--{key}")
            else:
                cmd.append(f"--{key}")
                cmd.append(str(value))

        return cmd
```

### タスク種別判定

```python
class TaskTypeClassifier:
    """タスクがScript実行可能か判定"""

    SCRIPT_TASKS = {
        "image_resize": "image/resize",
        "image_color_adjust": "image/color_adjust",
        "image_format_convert": "image/format_convert",
        "code_format": "code/format",
        "code_lint": "code/lint",
        "test_run": "test/run_tests",
        "build": "build/build",
    }

    def classify(self, task: "Task") -> str:
        """タスクの種別を判定"""
        # タスク名やキーワードから判定
        task_lower = task.objective.lower()

        if "リサイズ" in task_lower or "resize" in task_lower:
            return "script:image_resize"

        if "色調" in task_lower or "color" in task_lower:
            return "script:image_color_adjust"

        if "フォーマット" in task_lower or "format" in task_lower:
            if "画像" in task_lower or "image" in task_lower:
                return "script:image_format_convert"
            else:
                return "script:code_format"

        if "テスト実行" in task_lower or "run test" in task_lower:
            return "script:test_run"

        if "ビルド" in task_lower or "build" in task_lower:
            return "script:build"

        # Script実行不可 → LLMで処理
        return "llm"

    def get_script_name(self, task_type: str) -> Optional[str]:
        """Script名を取得"""
        if task_type.startswith("script:"):
            key = task_type.replace("script:", "")
            return self.SCRIPT_TASKS.get(key)
        return None
```

### WORKER内での分岐

```python
class Worker:
    def __init__(self, script_executor: ScriptExecutor, classifier: TaskTypeClassifier):
        self.script_executor = script_executor
        self.classifier = classifier

    async def execute(self, task: "Task") -> "Result":
        """タスクを実行"""

        # 種別を判定
        task_type = self.classifier.classify(task)

        if task_type.startswith("script:"):
            # Script実行
            return await self._execute_script(task, task_type)
        else:
            # LLM実行
            return await self._execute_llm(task)

    async def _execute_script(self, task: "Task", task_type: str) -> "Result":
        """Scriptでタスクを実行"""
        script_name = self.classifier.get_script_name(task_type)

        # タスクからScript引数を抽出
        args = self._extract_script_args(task)

        # 実行
        result = self.script_executor.execute(script_name, args)

        return Result(
            success=result.success,
            output=result.output,
            error=result.error,
            method="script",
            tokens_used=0,  # Scriptなのでトークン消費なし
            cost=0.0
        )

    async def _execute_llm(self, task: "Task") -> "Result":
        """LLMでタスクを実行"""
        # 通常のLLM処理
        pass
```

## コスト比較

| 処理 | LLM (トークン) | LLM (コスト) | Script | 速度比 |
|------|--------------|-------------|--------|--------|
| 画像リサイズ×10枚 | 5,000 | $0.015 | $0 | 100x |
| コードフォーマット | 2,000 | $0.006 | $0 | 50x |
| テスト実行 | 1,000 | $0.003 | $0 | 10x |
| 一括置換×100箇所 | 10,000 | $0.030 | $0 | 200x |

## 設定

```yaml
# config/mechanical_tasks.yaml

mechanical_tasks:
  enabled: true

  # 自動判定を有効化
  auto_classify: true

  # Script優先度
  prefer_script: true

  # カスタムマッピング
  mappings:
    - pattern: "画像.*リサイズ"
      script: "image/resize"
    - pattern: "フォーマット.*コード"
      script: "code/format"

  # フォールバック
  fallback_to_llm: true
```

## 監視

| メトリクス | 説明 |
|-----------|------|
| script_execution_count | Script実行回数 |
| script_success_rate | Script成功率 |
| tokens_saved | 節約されたトークン数 |
| cost_saved | 節約されたコスト |
