#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from typing import Optional, Tuple, Dict, Any

import urllib.request

DISPATCH = os.path.expanduser("~/lucy/tools/internet/tool_router.sh")

ALLOWED_TOOLS = {"search_web", "fetch_url", "fetch_url_v1"}

def post_chat(payload: dict) -> dict:
    # Ollama chat endpoint
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def extract_tool_call(text: str) -> Optional[Tuple[str, Dict[str, Any], str]]:
    """
    Find FIRST JSON object containing tool_call anywhere in the assistant text.
    Supports multi-line / pretty-printed JSON by scanning for balanced braces.
    Return (name, args, canonical_json_line).
    """
    if "tool_call" not in text:
        return None

    s = text
    n = len(s)

    def scan_json_obj(start: int) -> Optional[str]:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, n):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            else:
                if ch == '"':
                    in_str = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return s[start:i+1]
        return None

    for start in range(n):
        if s[start] != "{":
            continue
        cand = scan_json_obj(start)
        if not cand or "tool_call" not in cand:
            continue
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        tc = obj.get("tool_call")
        if not isinstance(tc, dict):
            continue
        name = tc.get("name")
        args = tc.get("arguments", {})
        if not isinstance(name, str):
            continue
        if not isinstance(args, dict):
            args = {}
        canonical = json.dumps(
            {"tool_call": {"name": name, "arguments": args}},
            ensure_ascii=False,
            separators=(",", ":")
        )
        return name, args, canonical

    return None
    """
    Find FIRST JSON object line containing tool_call. Return (name, args, json_line).
    Reject anything that isn't valid JSON with correct shape.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{") or "tool_call" not in line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        tc = obj.get("tool_call")
        if not isinstance(tc, dict):
            continue
        name = tc.get("name")
        args = tc.get("arguments", {})
        if not isinstance(name, str):
            continue
        if not isinstance(args, dict):
            args = {}
        return name, args, line
    return None

def sanitize_args(tool: str, args: Dict[str, Any], fallback_query: str) -> Dict[str, Any]:
    """
    Minimal v0 validator/repair.
    - search_web: requires query str, max_results int 1..10
    - fetch_url: requires url str, max_bytes int
    """
    out = dict(args or {})

    if tool == "search_web":
        q = out.get("query")
        if not isinstance(q, str) or not q.strip():
            out["query"] = fallback_query.strip()[:256]
        mr = out.get("max_results")
        if not isinstance(mr, int):
            mr = 5
        mr = max(1, min(10, mr))
        out["max_results"] = mr
        # domains optional, but if present must be list[str]
        dom = out.get("domains")
        if dom is not None:
            if not (isinstance(dom, list) and all(isinstance(x, str) for x in dom)):
                out.pop("domains", None)

    elif tool == "fetch_url_v1":
        url = out.get("url")
        if not isinstance(url, str) or not url.strip():
            out["url"] = fallback_query.strip()
        mb = out.get("max_bytes")
        if not isinstance(mb, int):
            mb = 200000
        mb = max(1000, min(2_000_000, mb))
        out["max_bytes"] = mb

    return out

def run_tool(tool: str, args: Dict[str, Any]) -> str:
    # Backward-compat alias: force v1 fetch envelope
    if tool == "fetch_url":
        tool = "fetch_url_v1"

    if tool not in ALLOWED_TOOLS:
        return json.dumps({"error": "tool_not_allowed", "name": tool})
    args_json = json.dumps(args, ensure_ascii=False)
    try:
        out = subprocess.check_output([DISPATCH, tool, args_json], text=True)
        return out.strip()
    except subprocess.CalledProcessError as e:
        # Dispatcher should already print JSON; keep stderr minimal.
        return (e.output or "").strip() or json.dumps({"error": "tool_failed", "code": e.returncode})

def main():
    if len(sys.argv) < 2:
        print("usage: lucy_chat_tools.py <runtime_model>")
        sys.exit(1)

    runtime_model = sys.argv[1]
    messages = []

    print("=== Local Lucy DEV (tools loop) ===")
    print(f"Model: {runtime_model}")
    print("Type /exit to quit.\n")

    while True:
        try:
            user = input(">>> ").strip()
        except EOFError:
            break

        if not user:
            continue
        if user == "/exit":
            break

        # If the user pastes tool-result-looking text, treat it as plain user text.
        messages.append({"role": "user", "content": user})

        tool_used_this_turn = False
        external_unverified_seen = False

        # up to 4 internal steps (tool call + final answer)
        for _step in range(4):
            resp = post_chat({"model": runtime_model, "messages": messages, "stream": False})
            assistant = resp.get("message", {}).get("content", "")
            assistant = "" if assistant is None else str(assistant)

            # Never allow the model to inject fake TOOL_RESULT into the transcript.
            if "TOOL_RESULT" in assistant:
                # Strip it; keep only what precedes it.
                assistant = assistant.split("TOOL_RESULT", 1)[0].rstrip()

            tc = extract_tool_call(assistant)
            # Recovery: model tried to emit a tool_call but JSON was malformed/truncated.
            if (tc is None) and ("tool_call" in assistant):
                messages.append({"role": "user", "content": "INSTRUCTION: Re-emit the tool_call as a SINGLE LINE of VALID JSON only. No prose. Example: {\"tool_call\":{\"name\":\"search_web\",\"arguments\":{\"query\":\"...\",\"max_results\":5}}}"} )
                continue



            if tc:
                name, args, json_line = tc

                # ENFORCE: store only the JSON tool_call line (not extra prose)
                messages.append({"role": "assistant", "content": json_line})
                print(json_line)

                # Enforce: only one tool call per user turn
                if tool_used_this_turn:
                    messages.append({"role": "user", "content": "TOOL_RESULT error {\"error\":\"too_many_tool_calls\"}"})
                    print('TOOL_RESULT error {"error":"too_many_tool_calls"}')
                    break

                # Step 2.3 fence: once external_unverified is seen, require synthesis-only
                if external_unverified_seen:
                    err = '{"error":"read_only_fence","detail":"external_unverified requires synthesis-only"}'
                    messages.append({"role": "user", "content": f"TOOL_RESULT error {err}"})
                    print(f"TOOL_RESULT error {err}")
                    break

                fallback_query = user
                args = sanitize_args(name, args, fallback_query)
                tool_out = run_tool(name, args)

                # Parse tool output (may be JSON)
                tool_obj = None
                try:
                    tool_obj = json.loads(tool_out)
                except Exception:
                    tool_obj = None

                # Hard stop on tool error
                if isinstance(tool_obj, dict) and tool_obj.get("error"):
                    print(tool_out)
                    break

                # Step 2.2 latch: trust_level from envelope
                trust_level = tool_obj.get("trust_level") if isinstance(tool_obj, dict) else None
                if trust_level == "external_unverified":
                    external_unverified_seen = True

                # Print tool result for transparency
                print(f"TOOL_RESULT {name} {tool_out}")

                # Inject tool output back to model as user message
                messages.append({"role": "user", "content": f"TOOL_RESULT {name} {tool_out}"})
                tool_used_this_turn = True

                # After tool result, require one synthesis answer only
                messages.append({"role": "user", "content": "INSTRUCTION: Now answer ONCE. Use ONLY the TOOL_RESULT. Cite URLs from results. No extra tool calls."})
                continue
            # no tool call => normal assistant output
            print(assistant)
            messages.append({"role": "assistant", "content": assistant})
            break

if __name__ == "__main__":
    main()
