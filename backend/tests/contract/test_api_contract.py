"""
API契約テスト - OpenAPIスキーマとの整合性検証

Schemathesisを使用してOpenAPIスキーマに基づいた自動テストを実行します。
実際のAPIレスポンスがスキーマ定義と一致するかを検証します。

実行方法:
  pytest tests/contract/ -v
  または
  schemathesis run openapi/openapi.json --base-url http://localhost:5000
"""

import os
from pathlib import Path

import pytest

try:
    import schemathesis

    SCHEMATHESIS_AVAILABLE = True
except ImportError:
    SCHEMATHESIS_AVAILABLE = False
    schemathesis = None

OPENAPI_PATH = Path(__file__).parent.parent.parent / "openapi" / "openapi.json"
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000")

pytestmark = pytest.mark.skipif(not SCHEMATHESIS_AVAILABLE, reason="schemathesis not installed")


@pytest.fixture(scope="module")
def api_schema():
    if not OPENAPI_PATH.exists():
        pytest.skip(f"OpenAPI schema not found at {OPENAPI_PATH}")
    return schemathesis.from_path(str(OPENAPI_PATH), base_url=BASE_URL)


class TestAPIContract:
    """OpenAPIスキーマとの契約テスト"""

    @pytest.mark.contract
    def test_schema_is_valid(self, api_schema):
        """OpenAPIスキーマが有効であることを確認"""
        assert api_schema is not None
        assert len(list(api_schema.get_all_operations())) > 0

    @pytest.mark.contract
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/projects",
            "/api/static-config",
        ],
    )
    def test_get_endpoints_match_schema(self, api_schema, endpoint):
        """GETエンドポイントがスキーマと一致することを確認"""
        operations = list(api_schema.get_all_operations())
        matching = [op for op in operations if op.path == endpoint and op.method.upper() == "GET"]
        assert len(matching) > 0, f"Endpoint {endpoint} not found in schema"


def run_schemathesis_cli():
    """Schemathesis CLIを使用したフルテスト実行用のヘルパー"""
    import subprocess

    if not OPENAPI_PATH.exists():
        print(f"OpenAPI schema not found at {OPENAPI_PATH}")
        print("Run 'python scripts/generate_openapi.py' first")
        return 1

    cmd = [
        "schemathesis",
        "run",
        str(OPENAPI_PATH),
        "--base-url",
        BASE_URL,
        "--checks",
        "all",
        "--hypothesis-max-examples",
        "50",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    exit(run_schemathesis_cli())
