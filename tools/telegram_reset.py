import json
import os
from pathlib import Path
from urllib.request import urlopen, Request

def load_env(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip("\"").strip("'")
        data[key] = val
    return data


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def api_call(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    env = load_env(root / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN missing")
        return 1

    print(f"TELEGRAM_BOT_TOKEN: {mask_token(token)}")

    info = api_call(token, "getWebhookInfo")
    print("getWebhookInfo:")
    print(json.dumps(info, ensure_ascii=False, indent=2))

    result = info.get("result", {}) if isinstance(info, dict) else {}
    url = result.get("url") or ""
    pending = result.get("pending_update_count") or 0
    active = bool(url) or (isinstance(pending, int) and pending > 0)

    if active:
        cleared = api_call(token, "deleteWebhook?drop_pending_updates=true")
        print("deleteWebhook:")
        print(json.dumps(cleared, ensure_ascii=False, indent=2))
        info2 = api_call(token, "getWebhookInfo")
        print("getWebhookInfo(after):")
        print(json.dumps(info2, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
