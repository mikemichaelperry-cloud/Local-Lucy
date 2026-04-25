#!/usr/bin/env python3
import json
import hashlib
import time
from pathlib import Path
import requests
import subprocess
import re
def _has_hebrew(text: str) -> bool:
    return bool(re.search(r"[\u0590-\u05FF]", text))

def _is_identity_query(text: str) -> bool:
    t = text.strip().lower()

    # English identity / capability questions (treat as identity boilerplate triggers)
    exact = {
        "who are you?", "who are you", "who r u", "who r you", "whoru",
        "what are you?", "what are you",
        "how do you work?", "how do you work",
        "how do you function?", "how do you function",
        "how are you functioning?", "how are you functioning",
        "how do you operate?", "how do you operate",
        "how are you working?", "how are you working",
        "what do you do?", "what do you do",
        "what is your function?", "what is your function",
        "what's your function?", "what's your function",
    }
    if t in exact:
        return True

    # Also catch common phrasing with a light substring check
    substrings = [
        "how do you work",
        "how do you function",
        "how are you functioning",
        "how do you operate",
        "how does this work",
        "what are you",
        "who are you",
        "your function",
    ]
    if any(p in t for p in substrings):
        return True

    # Hebrew variants
    ht = text.strip()
    heb_exact = {
        "מי את?", "מי את", "מי אתה?", "מי אתה", "מי אתם?", "מי אתם",
        "איך את פועלת?", "איך את פועלת", "איך אתה פועל?", "איך אתה פועל",
        "איך זה עובד?", "איך זה עובד",
        "איך את עובדת?", "איך את עובדת", "איך אתה עובד?", "איך אתה עובד",
        "מה את?", "מה את", "מה אתה?", "מה אתה",
    }
    if ht in heb_exact:
        return True

    return False


# -------------------------
# CONFIG
# -------------------------
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "local-lucy:latest"

BASE_DIR = Path("/home/mike/lucy")
CONFIG_DIR = BASE_DIR / "config"
MEMORY_DIR = BASE_DIR / "memory"
RUNTIME_DIR = BASE_DIR / "runtime"
LOG_DIR = BASE_DIR / "logs"

KEEL_FILE = CONFIG_DIR / "keel.yaml"
SYSTEM_PROMPT_FILE = CONFIG_DIR / "system_prompt.txt"
MODES_DIR = CONFIG_DIR / "modes"
MEMORY_FILE = MEMORY_DIR / "memory.txt"
STATE_FILE = RUNTIME_DIR / "state.json"

CHAT_LOG = LOG_DIR / "chat.log"
ERROR_LOG = LOG_DIR / "errors.log"

# -------------------------
# UTILITIES
# -------------------------
def log_append(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"mode": "mike"}

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

# -------------------------
# COMMAND PARSING (v0)
# -------------------------
def parse_command(user_input: str):
    txt = user_input.strip()
    low = txt.lower()
    if low.startswith("mode:"):
        return ("mode", txt.split(":", 1)[1].strip())
    if low.startswith("memory:"):
        return ("memory", txt.split(":", 1)[1].strip())
    return (None, None)

# -------------------------
# PROMPT ASSEMBLY
# -------------------------
def build_prompt(user_input: str, state: dict) -> str:
    keel = load_text(KEEL_FILE)
    system_base = load_text(SYSTEM_PROMPT_FILE)

    mode_name = state.get("mode", "mike")
    mode_file = MODES_DIR / f"{mode_name}.yaml"
    mode_text = load_text(mode_file)

    memory_text = load_text(MEMORY_FILE)

    prompt_parts = []

    # 1) Keel
    if keel:
        prompt_parts.append(f"SYSTEM:\n{keel}")

    # 2) Base system prompt
    if system_base:
        prompt_parts.append(f"SYSTEM:\n{system_base}")

    # 3) Mode overlay
    if mode_text:
        prompt_parts.append(f"SYSTEM (MODE: {mode_name}):\n{mode_text}")

    # 4) Memory snapshot (read-only for this reply)
    if memory_text:
        prompt_parts.append(
            "SYSTEM:\n"
            "MEMORY_SNAPSHOT_BEGIN\n"
            f"{memory_text}\n"
            "MEMORY_SNAPSHOT_END\n"
            "Memory snapshot is READ-ONLY reference for this reply. "
            "Do NOT claim persistent memory is enabled unless explicitly stated by the user."
        )

    # 5) Authoritative runtime state (do not guess)
    prompt_parts.append(
        f"SYSTEM:\nCURRENT_MODE: {mode_name}\n"
        "Do not guess mode. Use CURRENT_MODE only."
    )

    # 6) User
    prompt_parts.append(f"USER:\n{user_input}")

    return "\n\n".join(prompt_parts)

# -------------------------
# MODEL CALL
# -------------------------
def call_model(prompt: str) -> str:
    payload = {"model": DEFAULT_MODEL, "prompt": prompt, "stream": False}
    r = requests.post(OLLAMA_URL, json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("response", "")

# -------------------------
# OUTPUT CHECKS (v0)
# -------------------------
def post_check(output: str) -> bool:
    forbidden = [
        "i will modify my code",
        "i will change my rules",
        "i will run a tool",
        "executing command",
    ]
    lower = output.lower()
    return not any(f in lower for f in forbidden)

# -------------------------
# TURN HANDLER (v0.1 hardened)
# -------------------------
def handle_turn(user_input: str) -> str:
    # Deterministic identity response (do not call model)
    if _is_identity_query(user_input):
        return "אני לוסי." if _has_hebrew(user_input) else "I'm Lucy."

    state = load_state()

    cmd, arg = parse_command(user_input)

    if cmd == "mode":
        allowed = {pp.stem for pp in MODES_DIR.glob("*.yaml")}
        if arg not in allowed:
            return f"Unknown mode '{arg}'. Available: {', '.join(sorted(allowed))}"
        state["mode"] = arg
        save_state(state)
        return f"Mode switched to '{arg}'."

    if cmd == "memory":
        sub = (arg or "").strip()
        if not sub or sub in {"help", "?"}:
            return ("memory: list  -> show pending proposals\n"
                    "memory: propose <text> -> create a proposal (human must approve)")

        if sub == "list":
            inbox = (MEMORY_DIR / "inbox")
            if not inbox.exists():
                return "Memory inbox not found."
            files = sorted(inbox.glob("*.txt"))
            if not files:
                return "No pending memory proposals."
            lines = ["Pending proposals:"]
            for p in files[:50]:
                lines.append(f"- {p.name}")
            if len(files) > 50:
                lines.append(f"(+{len(files)-50} more)")
            return "\n".join(lines)

        if sub.startswith("propose "):
            text = sub[len("propose "):].strip()
            if not text:
                return "Usage: memory: propose <text>"
            # Call human-owned proposer script
            script = BASE_DIR / "tools" / "lucy-mem-propose.sh"
            if not script.exists():
                return "Propose script missing: tools/lucy-mem-propose.sh"
            try:
                out = subprocess.check_output([str(script), text], stderr=subprocess.STDOUT, text=True)
                return out.strip()
            except subprocess.CalledProcessError as e:
                return f"Propose failed: {e.output.strip()}"

        return "Unknown memory subcommand. Try: memory: help"

    prompt = build_prompt(user_input, state)
    prompt_hash = sha256(prompt)

    try:
        start = time.time()
        output = call_model(prompt)
        elapsed = time.time() - start

        if not post_check(output):
            raise RuntimeError("Output violated keel constraints")

        log_append(
            CHAT_LOG,
            json.dumps(
                {
                    "ts": time.time(),
                    "mode": state.get("mode"),
                    "prompt_hash": prompt_hash,
                    "latency_s": round(elapsed, 3),
                    "user": user_input,
                    "output": output,
                },
                ensure_ascii=False,
            ),
        )
        return output

    except Exception as e:
        log_append(ERROR_LOG, f"{time.time()} | {type(e).__name__}: {str(e)}")
        return "I can’t proceed with that request. Please clarify or adjust."

# -------------------------
# CLI ENTRY
# -------------------------
if __name__ == "__main__":
    while True:
        try:
            user_input = input("> ")
            if user_input.strip().lower() in ("exit", "quit"):
                break
            print(handle_turn(user_input))
        except KeyboardInterrupt:
            break
