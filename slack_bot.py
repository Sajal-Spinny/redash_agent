"""
Redash Data Fetcher — Slack Bot
--------------------------------
Bridges Slack messages to the Claude-powered Redash agent.
Claude uses run_query.py as a tool, so it can actually execute SQL
and return results inline in Slack.

Setup:
  pip install slack-bolt anthropic pandas tabulate

Env vars required (add to .env or setx on Windows):
  SLACK_BOT_TOKEN   — xoxb-... (Bot User OAuth Token)
  SLACK_APP_TOKEN   — xapp-... (App-Level Token, for Socket Mode)
  ANTHROPIC_API_KEY — sk-ant-...
  DORIS_HOST / DORIS_PORT / DORIS_USER / DORIS_PASSWORD  (existing)

Run:
  python slack_bot.py
"""

import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Optional, List, Dict

import anthropic
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# ── Paths (adjust if your repo root differs) ──────────────────────────────────
REPO_ROOT     = Path(r"C:/Users/Sajal/Desktop/redash-agent")
CLAUDE_MD     = REPO_ROOT / "CLAUDE.md"
MEMORY_NOTES  = REPO_ROOT / "memory_notes.md"
RUN_QUERY     = REPO_ROOT / "scripts" / "run_query.py"
OUTPUT_DIR    = REPO_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── System prompt: merge CLAUDE.md + memory_notes ────────────────────────────
def build_system_prompt() -> str:
    parts = []
    for f in [CLAUDE_MD, MEMORY_NOTES]:
        if f.exists():
            parts.append(f.read_text(encoding="utf-8"))
        else:
            print(f"[WARN] {f} not found — skipping")
    return "\n\n---\n\n".join(parts)

SYSTEM_PROMPT = build_system_prompt()

# ── Tool definition exposed to Claude ─────────────────────────────────────────
TOOLS = [
    {
        "name": "run_sql_query",
        "description": (
            "Execute a read-only SQL query against Doris via run_query.py. "
            "Returns the result as a plain-text table. "
            "Optionally saves to a CSV file in output/ and returns the path. "
            "Only SELECT / WITH / SHOW / DESCRIBE are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute."
                },
                "csv_filename": {
                    "type": "string",
                    "description": (
                        "Optional. If provided, results are also saved to "
                        "output/<csv_filename>.csv"
                    )
                }
            },
            "required": ["sql"]
        }
    }
]

# ── Tool executor ─────────────────────────────────────────────────────────────
def execute_run_query(sql: str, csv_filename: Optional[str] = None) -> str:
    """Call scripts/run_query.py and return stdout or an error string."""
    cmd = ["python", str(RUN_QUERY), sql]
    if csv_filename:
        safe_name = csv_filename.replace("/", "_").replace("\\", "_")
        if not safe_name.endswith(".csv"):
            safe_name += ".csv"
        csv_path = OUTPUT_DIR / safe_name
        cmd += ["--csv", str(csv_path)]

    env = {**os.environ}  # inherit DORIS_* credentials from environment

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            cwd=str(REPO_ROOT)
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip() or "Unknown error"
            return f"[Query error]\n{err}"
        if csv_filename:
            output += f"\n\n📁 Saved to output/{safe_name}"
        return output or "(No rows returned)"
    except subprocess.TimeoutExpired:
        return "[Error] Query timed out after 120 seconds."
    except Exception as e:
        return f"[Error] {e}"

# ── Agentic loop: Claude ↔ tool calls ─────────────────────────────────────────
def run_agent(user_message: str, history: Optional[List[Dict]] = None) -> str:
    """
    Runs the Claude agentic loop for one user turn.
    `history` is a list of prior {role, content} dicts for multi-turn context.
    Returns Claude's final text reply.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = (history or []) + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        # Collect any text blocks for a potential final reply
        text_blocks = [b.text for b in response.content if b.type == "text"]

        if response.stop_reason == "end_turn":
            return "\n".join(text_blocks) or "(No response)"

        if response.stop_reason == "tool_use":
            # Append Claude's response (may include text + tool_use blocks)
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call and collect results
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_input = block.input
                print(f"[Tool] {block.name} called with: {json.dumps(tool_input)[:200]}")

                if block.name == "run_sql_query":
                    result_text = execute_run_query(
                        sql=tool_input["sql"],
                        csv_filename=tool_input.get("csv_filename")
                    )
                else:
                    result_text = f"[Error] Unknown tool: {block.name}"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text
                })

            messages.append({"role": "user", "content": tool_results})
            # Loop back — Claude will now interpret the tool results
            continue

        # Unexpected stop reason
        return "\n".join(text_blocks) or f"[Stopped: {response.stop_reason}]"

# ── Per-user conversation history (in-memory, resets on restart) ───────────────
# Keyed by Slack user_id. Stores last N turns to give Claude context.
MAX_HISTORY_TURNS = 6  # 3 user + 3 assistant turns

conversation_history: Dict[str, List[Dict]] = {}
history_lock = threading.Lock()

def get_history(user_id: str) -> List[Dict]:
    with history_lock:
        return list(conversation_history.get(user_id, []))

def update_history(user_id: str, user_msg: str, assistant_msg: str):
    with history_lock:
        hist = conversation_history.setdefault(user_id, [])
        hist.append({"role": "user", "content": user_msg})
        hist.append({"role": "assistant", "content": assistant_msg})
        # Keep only last MAX_HISTORY_TURNS turns
        if len(hist) > MAX_HISTORY_TURNS * 2:
            conversation_history[user_id] = hist[-(MAX_HISTORY_TURNS * 2):]

def clear_history(user_id: str):
    with history_lock:
        conversation_history.pop(user_id, None)

# ── Slack app ──────────────────────────────────────────────────────────────────
app = App(token=os.environ["SLACK_BOT_TOKEN"])

@app.message("")
def handle_message(message, say, client):
    """Handle any DM or channel message where the bot is mentioned."""
    user_id  = message.get("user", "unknown")
    channel  = message["channel"]
    text     = message.get("text", "").strip()

    # Skip bot's own messages
    if message.get("bot_id"):
        return

    # /reset command to clear conversation context
    if text.lower() in ("/reset", "reset", "clear"):
        clear_history(user_id)
        say("🗑️ Conversation history cleared.")
        return

    # Post a "thinking" reaction so the user knows it's working
    try:
        client.reactions_add(channel=channel, name="hourglass_flowing_sand",
                             timestamp=message["ts"])
    except Exception:
        pass

    history = get_history(user_id)
    reply   = run_agent(text, history)
    update_history(user_id, text, reply)

    # Remove thinking reaction
    try:
        client.reactions_remove(channel=channel, name="hourglass_flowing_sand",
                                timestamp=message["ts"])
    except Exception:
        pass

    # Slack has a 3000-char limit per block; split if needed
    if len(reply) <= 3000:
        say(reply)
    else:
        # Send in chunks
        chunks = [reply[i:i+3000] for i in range(0, len(reply), 3000)]
        for chunk in chunks:
            say(chunk)

@app.event("app_mention")
def handle_mention(event, say, client):
    """Also respond when @mentioned in a channel."""
    # Strip the mention tag and delegate to the same handler
    text    = event.get("text", "")
    user_id = event.get("user", "unknown")
    channel = event["channel"]

    # Remove <@BOTID> from text
    import re
    clean_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    if not clean_text:
        say("Yes? Ask me for data — e.g. _city-wise deliveries MTD_")
        return

    try:
        client.reactions_add(channel=channel, name="hourglass_flowing_sand",
                             timestamp=event["ts"])
    except Exception:
        pass

    history = get_history(user_id)
    reply   = run_agent(clean_text, history)
    update_history(user_id, clean_text, reply)

    try:
        client.reactions_remove(channel=channel, name="hourglass_flowing_sand",
                                timestamp=event["ts"])
    except Exception:
        pass

    if len(reply) <= 3000:
        say(reply)
    else:
        chunks = [reply[i:i+3000] for i in range(0, len(reply), 3000)]
        for chunk in chunks:
            say(chunk)

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    required_env = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "ANTHROPIC_API_KEY",
                    "DORIS_HOST", "DORIS_USER", "DORIS_PASSWORD"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"[Error] Missing env vars: {', '.join(missing)}")

    print("🤖 Redash Data Fetcher bot starting (Socket Mode)…")
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()