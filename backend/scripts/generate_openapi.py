import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openapi.generator import get_openapi_json


def main():
    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "langgraph-studio",
        "src",
        "types",
        "openapi.json",
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    spec = get_openapi_json()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
    print(f"OpenAPI spec generated: {output_path}")


if __name__ == "__main__":
    main()
