"""ローカルComfyUIプロバイダー - 画像生成専用"""

import time
import requests
from typing import List, Optional, Dict, Any, Iterator
from .base import AIProvider, AIProviderConfig, ChatMessage, ChatResponse, StreamChunk, ModelInfo


class LocalComfyUIProvider(AIProvider):
    """ローカルComfyUIプロバイダー（画像生成専用）"""

    DEFAULT_BASE_URL = "http://127.0.0.1:8188"

    @property
    def provider_id(self) -> str:
        return "local-comfyui"

    @property
    def display_name(self) -> str:
        return "ComfyUI (ローカル)"

    def _get_base_url(self) -> str:
        return self.config.base_url or self.DEFAULT_BASE_URL

    def get_available_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                id="comfyui-default",
                name="ComfyUI Default Workflow",
                max_tokens=0,
                supports_vision=False,
                supports_tools=False,
                input_cost_per_1k=0,
                output_cost_per_1k=0,
            ),
        ]

    def chat(
        self, messages: List[ChatMessage], model: str, max_tokens: int = 1024, temperature: float = 0.7, **kwargs
    ) -> ChatResponse:
        raise NotImplementedError("ComfyUIは画像生成専用です。chat()メソッドはサポートされていません。")

    def chat_stream(
        self, messages: List[ChatMessage], model: str, max_tokens: int = 1024, temperature: float = 0.7, **kwargs
    ) -> Iterator[StreamChunk]:
        raise NotImplementedError("ComfyUIは画像生成専用です。chat_stream()メソッドはサポートされていません。")

    def test_connection(self) -> Dict[str, Any]:
        base_url = self._get_base_url()
        try:
            response = requests.get(f"{base_url}/system_stats", timeout=self.config.timeout)
            if response.status_code == 200:
                stats = response.json()
                return {
                    "success": True,
                    "message": f"ComfyUI接続成功 (GPU: {stats.get('devices', [{}])[0].get('name', '不明')})",
                }
            return {"success": False, "message": f"ComfyUI接続失敗: HTTP {response.status_code}"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "message": f"ComfyUIに接続できません ({base_url})"}
        except requests.exceptions.Timeout:
            return {"success": False, "message": "ComfyUI接続タイムアウト"}
        except Exception as e:
            return {"success": False, "message": f"ComfyUI接続エラー: {str(e)}"}

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: int = -1,
        workflow: Optional[Dict] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        base_url = self._get_base_url()
        if workflow:
            prompt_data = workflow
        else:
            prompt_data = self._build_default_workflow(prompt, negative_prompt, width, height, steps, cfg_scale, seed)
        try:
            response = requests.post(f"{base_url}/prompt", json={"prompt": prompt_data}, timeout=self.config.timeout)
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "prompt_id": result.get("prompt_id"),
                    "message": "画像生成リクエストを送信しました",
                }
            return {"success": False, "message": f"画像生成リクエスト失敗: HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "message": f"画像生成エラー: {str(e)}"}

    def _build_default_workflow(
        self, prompt: str, negative_prompt: str, width: int, height: int, steps: int, cfg_scale: float, seed: int
    ) -> Dict:
        return {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed if seed >= 0 else int(time.time()),
                    "steps": steps,
                    "cfg": cfg_scale,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0],
                },
            },
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["4", 1]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
        }

    def get_queue_status(self) -> Dict[str, Any]:
        base_url = self._get_base_url()
        try:
            response = requests.get(f"{base_url}/queue", timeout=self.config.timeout)
            if response.status_code == 200:
                return {"success": True, "queue": response.json()}
            return {"success": False, "message": f"キュー取得失敗: HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "message": f"キュー取得エラー: {str(e)}"}

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        base_url = self._get_base_url()
        try:
            response = requests.get(f"{base_url}/history/{prompt_id}", timeout=self.config.timeout)
            if response.status_code == 200:
                return {"success": True, "history": response.json()}
            return {"success": False, "message": f"履歴取得失敗: HTTP {response.status_code}"}
        except Exception as e:
            return {"success": False, "message": f"履歴取得エラー: {str(e)}"}

    def validate_config(self) -> bool:
        return True
