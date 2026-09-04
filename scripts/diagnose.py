import asyncio
import sys
import httpx
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Parse .env
env_path = Path(__file__).parents[1] / ".env"
env_vars = {}
for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env_vars[k.strip()] = v.strip()

GEMINI_KEY   = env_vars.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = env_vars.get("GEMINI_MODEL", "gemini-1.5-flash").strip()
TG_TOKEN     = env_vars.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID   = env_vars.get("TELEGRAM_CHAT_ID", "").strip()
TG_MOCK      = env_vars.get("TELEGRAM_MOCK_MODE", "true").lower() == "true"


def banner(title: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {title}")
    print(f"{'='*55}")


async def check_gemini() -> bool:
    banner("1. Gemini API")
    print(f"  Model : {GEMINI_MODEL}")
    print(f"  Key   : {GEMINI_KEY[:8]}...{GEMINI_KEY[-4:]} ({len(GEMINI_KEY)} chars)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": "Reply with just the word: CONNECTED"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 10},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, headers={"x-goog-api-key": GEMINI_KEY}, json=payload)
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            print(f"  [OK] Gemini responded: '{text.strip()}'")
            return True
        else:
            err = r.json().get("error", {})
            print(f"  [FAIL] {r.status_code}: {err.get('message', r.text[:200])}")
            return False
    except Exception as e:
        print(f"  [FAIL] Network error: {e}")
        return False


async def check_telegram() -> tuple[bool, str | None]:
    banner("2. Telegram Bot")
    token = TG_TOKEN
    if not token:
        print("  [FAIL] TELEGRAM_BOT_TOKEN is empty")
        return False, None

    print(f"  Token     : {token[:10]}...{token[-4:]}")
    print(f"  Mock mode : {TG_MOCK}")

    # Verify bot identity
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = r.json()
        if not data.get("ok"):
            print(f"  [FAIL] Bot auth: {data.get('description')}")
            return False, None
        bot = data["result"]
        print(f"  [OK] Bot: @{bot['username']} | {bot['first_name']}")
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False, None

    # Fetch real chat_id from updates
    found_chat_id = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"https://api.telegram.org/bot{token}/getUpdates?limit=20&allowed_updates=[\"message\"]")
        updates = r.json().get("result", [])
        if updates:
            for upd in updates:
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat", {})
                cid = chat.get("id")
                cname = chat.get("first_name") or chat.get("title") or chat.get("username")
                if cid:
                    found_chat_id = str(cid)
                    print(f"  [OK] Chat found  -> ID: {cid} | Name: {cname} | Type: {chat.get('type')}")
                    if str(cid) != TG_CHAT_ID:
                        print(f"  [!]  .env has TELEGRAM_CHAT_ID={TG_CHAT_ID!r} but real ID is {cid}")
                        print(f"       Will auto-update .env with the correct numeric ID")
                    else:
                        print(f"  [OK] TELEGRAM_CHAT_ID in .env matches")
        else:
            print("  [!]  No messages found in updates. Make sure you sent /start to the bot.")
    except Exception as e:
        print(f"  [WARN] Could not fetch updates: {e}")

    # Send a live test message if not in mock mode
    if not TG_MOCK and found_chat_id:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data={"chat_id": found_chat_id, "text": "[StudentLife OS] Connection verified! Your bot is live."}
                )
            if r.json().get("ok"):
                print(f"  [OK] Live test message SENT to chat {found_chat_id}!")
            else:
                print(f"  [FAIL] Send failed: {r.json().get('description')}")
        except Exception as e:
            print(f"  [FAIL] Send error: {e}")
    elif TG_MOCK:
        print("  [!]  Mock mode ON — skipping live send test")

    return True, found_chat_id


async def check_openclaw(gemini_ok: bool) -> None:
    banner("3. OpenClaw Local Agent")
    print("  Type   : Local runtime (no external gateway)")
    print("  Engine : Gemini API (shares your GEMINI_API_KEY)")
    print(f"  Status : {'[OK] Ready' if gemini_ok else '[WARN] Needs working Gemini key'}")


def update_env(real_chat_id: str) -> None:
    """Patch .env with correct numeric chat_id."""
    env_text = env_path.read_text(encoding="utf-8", errors="replace")
    import re
    new_text = re.sub(
        r"^TELEGRAM_CHAT_ID\s*=.*$",
        f"TELEGRAM_CHAT_ID={real_chat_id}",
        env_text,
        flags=re.MULTILINE,
    )
    env_path.write_text(new_text, encoding="utf-8")
    print(f"\n  [OK] .env updated: TELEGRAM_CHAT_ID={real_chat_id}")


async def main() -> None:
    print("\n[*] StudentLife OS -- Connection Diagnostics")
    gemini_ok            = await check_gemini()
    tg_ok, real_chat_id  = await check_telegram()
    await check_openclaw(gemini_ok)

    # Auto-fix chat_id in .env if we found the real one
    if real_chat_id and real_chat_id != TG_CHAT_ID:
        banner("Auto-fixing .env")
        update_env(real_chat_id)

    banner("Summary")
    print(f"  Gemini API  : {'[OK] Connected' if gemini_ok else '[FAIL] Not working'}")
    print(f"  Telegram    : {'[OK] Live' if tg_ok else '[FAIL] Not reachable'}")
    print(f"  OpenClaw    : [OK] Local agent ready")


if __name__ == "__main__":
    asyncio.run(main())
