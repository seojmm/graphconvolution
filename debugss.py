# debug_mcp_tools.py
import os
import json
from pathlib import Path

from MCPs.kakao_mcp import PlayMCPClient


def load_dotenv_from_project_root() -> None:
    """
    graphconvolution/.env 파일을 직접 읽어서 os.environ에 채운다.
    python-dotenv 같은 외부 패키지 없이 동작.
    """
    root = Path(__file__).resolve().parent  # debug_mcp_tools.py가 있는 폴더 (graphconvolution)
    env_path = root / ".env"

    if not env_path.exists():
        print("[DEBUG] .env 파일을 찾지 못했습니다:", env_path)
        return

    print("[DEBUG] .env 로드:", env_path)
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # 이미 설정된 env가 없으면 주입
            if key and key not in os.environ:
                os.environ[key] = value


def main():
    load_dotenv_from_project_root()

    print("[DEBUG] PLAY_MCP_TOOLBOX_URL =", os.getenv("PLAY_MCP_TOOLBOX_URL"))
    print("[DEBUG] PLAY_MCP_TOKEN exists? =", bool(os.getenv("PLAY_MCP_TOKEN")))

    client = PlayMCPClient()

    resp = client.call("tools/list", {})
    print("=== tools/list raw ===")
    print(json.dumps(resp, indent=2, ensure_ascii=False))

    tools = resp.get("tools", []) if isinstance(resp, dict) else []

    print("\n=== Tool names ===")
    for t in tools:
        name = t.get("name")
        desc = t.get("description", "")
        print(f"- {name} :: {desc}")

    print("\n=== Candidate ETA tools (Transit/ETA/Map 포함) ===")
    for t in tools:
        name = t.get("name", "")
        if not name:
            continue
        if "Transit" in name or "ETA" in name or "Map" in name:
            print(f"\n--- Tool: {name} ---")
            print("description:", t.get("description"))
            print("inputSchema:")
            print(json.dumps(t.get("inputSchema"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
