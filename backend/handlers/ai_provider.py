"""AI Provider API - AIプロバイダーの接続テスト"""
import time
from flask import Flask, jsonify, request
from config import get_config


def register_ai_provider_routes(app: Flask):
    """Register AI provider related routes"""

    @app.route('/api/ai-providers/test', methods=['POST'])
    def test_ai_provider():
        """Test connection to an AI provider"""
        data = request.get_json()

        if not data:
            return jsonify({"error": "Request body is required"}), 400

        provider_type = data.get('providerType', '')
        config_data = data.get('config', {})

        if not provider_type:
            return jsonify({"error": "providerType is required"}), 400

        start_time = time.time()

        try:
            if provider_type == 'anthropic':
                result = _test_anthropic(config_data)
            elif provider_type == 'openai':
                result = _test_openai(config_data)
            elif provider_type == 'mock':
                # Mock provider always succeeds
                result = {
                    "success": True,
                    "message": "モック接続: 正常に接続できました"
                }
            else:
                return jsonify({
                    "success": False,
                    "message": f"未対応のプロバイダー: {provider_type}"
                }), 400

            latency = int((time.time() - start_time) * 1000)
            result["latency"] = latency

            return jsonify(result)

        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            return jsonify({
                "success": False,
                "message": f"接続エラー: {str(e)}",
                "latency": latency
            })


def _test_anthropic(config_data: dict) -> dict:
    """Test Anthropic API connection"""
    api_key = config_data.get('apiKey', '')

    if not api_key:
        # Try to get from environment
        app_config = get_config()
        api_key = app_config.agent.anthropic_api_key

    if not api_key:
        return {
            "success": False,
            "message": "APIキーが設定されていません"
        }

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)

        # Make a minimal API call to test connection
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )

        return {
            "success": True,
            "message": "Anthropic API: 正常に接続できました"
        }

    except anthropic.AuthenticationError:
        return {
            "success": False,
            "message": "認証エラー: APIキーが無効です"
        }
    except anthropic.RateLimitError:
        return {
            "success": False,
            "message": "レート制限: しばらく待ってから再試行してください"
        }
    except anthropic.APIConnectionError:
        return {
            "success": False,
            "message": "接続エラー: APIサーバーに接続できません"
        }
    except ImportError:
        return {
            "success": False,
            "message": "anthropicパッケージがインストールされていません"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"エラー: {str(e)}"
        }


def _test_openai(config_data: dict) -> dict:
    """Test OpenAI API connection"""
    api_key = config_data.get('apiKey', '')

    if not api_key:
        return {
            "success": False,
            "message": "APIキーが設定されていません"
        }

    try:
        import openai

        client = openai.OpenAI(api_key=api_key)

        # Make a minimal API call to test connection
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )

        return {
            "success": True,
            "message": "OpenAI API: 正常に接続できました"
        }

    except openai.AuthenticationError:
        return {
            "success": False,
            "message": "認証エラー: APIキーが無効です"
        }
    except openai.RateLimitError:
        return {
            "success": False,
            "message": "レート制限: しばらく待ってから再試行してください"
        }
    except openai.APIConnectionError:
        return {
            "success": False,
            "message": "接続エラー: APIサーバーに接続できません"
        }
    except ImportError:
        return {
            "success": False,
            "message": "openaiパッケージがインストールされていません"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"エラー: {str(e)}"
        }
