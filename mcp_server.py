"""
Redash Data Fetcher — MCP Server
Exposes Doris query execution and knowledge-base search as MCP tools
so this agent works as a Claude.ai connector.

Requirements:
    pip install mcp pymysql pandas

Usage (stdio transport — default for Claude.ai):
    python mcp_server.py

Usage (SSE transport — for remote/hosted deployments):
    python mcp_server.py --transport sse --port 8000
"""

import argparse
import os
import re
import sys
import textwrap
from pathlib import Path

import pandas as pd
import pymysql
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server init
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="redash-doris-agent",
    description=(
        "Query Spinny's Doris warehouse using proven Redash SQL patterns. "
        "Tools: run_sql, search_knowledge, get_memory_notes."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent          # adjust if you move this file
KNOWLEDGE_FILE = REPO_ROOT / "knowledge" / "redash_queries.md"
MEMORY_FILE    = REPO_ROOT / "memory_notes.md"

BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

def _get_conn():
    """Open a fresh PyMySQL connection using env-var credentials."""
    return pymysql.connect(
        host=os.environ["DORIS_HOST"],
        port=int(os.environ.get("DORIS_PORT", 9030)),
        user=os.environ["DORIS_USER"],
        password=os.environ["DORIS_PASSWORD"],
        database=os.environ.get("DORIS_DB", ""),
        connect_timeout=30,
        charset="utf8mb4",
    )


def _df_to_markdown(df: pd.DataFrame, max_rows: int = 200) -> str:
    """Convert a DataFrame to a markdown table string."""
    if df.empty:
        return "_No rows returned._"
    if len(df) > max_rows:
        note = f"\n\n> ⚠️ Showing first {max_rows} of {len(df)} rows."
        df = df.head(max_rows)
    else:
        note = ""
    header = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep    = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows   = [
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    ]
    return "\n".join([header, sep] + rows) + note


# ---------------------------------------------------------------------------
# Tool 1 — run_sql
# ---------------------------------------------------------------------------
@mcp.tool()
def run_sql(
    sql: str,
    limit: int = 500,
) -> str:
    """
    Execute a read-only SQL query against Spinny's Doris warehouse and return
    results as a Markdown table.

    Args:
        sql:   A SELECT / WITH / SHOW / DESCRIBE statement.
               INSERT / UPDATE / DELETE etc. are blocked.
        limit: Safety cap on rows returned (default 500, max 2000).
               If your query already has LIMIT, this is ignored.

    Returns:
        Markdown table of results, row count, and any warnings.
    """
    # Safety: block write operations
    if BLOCKED.search(sql):
        return (
            "❌ **Blocked**: Only SELECT / WITH / SHOW / DESCRIBE are allowed. "
            "This query contains a write operation."
        )

    # Auto-add LIMIT if not present and it's a SELECT
    if re.search(r"\bSELECT\b", sql, re.IGNORECASE) and not re.search(
        r"\bLIMIT\b", sql, re.IGNORECASE
    ):
        cap = min(int(limit), 2000)
        sql = sql.rstrip("; \n") + f"\nLIMIT {cap}"

    try:
        conn = _get_conn()
        df = pd.read_sql(sql, conn)
        conn.close()
    except Exception as exc:
        return f"❌ **Query error**: {exc}\n\n```sql\n{sql}\n```"

    row_count = len(df)
    table = _df_to_markdown(df)
    return (
        f"**Rows returned:** {row_count}\n\n"
        f"{table}\n\n"
        f"<details><summary>SQL used</summary>\n\n```sql\n{sql}\n```\n</details>"
    )


# ---------------------------------------------------------------------------
# Tool 2 — search_knowledge
# ---------------------------------------------------------------------------
@mcp.tool()
def search_knowledge(keywords: str, max_results: int = 5) -> str:
    """
    Search knowledge/redash_queries.md for queries matching the given keywords.
    Use this before writing any SQL to find the best existing Redash query to
    adapt, as required by the agent's CLAUDE.md rules.

    Args:
        keywords:    Space- or comma-separated terms to search for
                     (e.g. "delivery city refurb", "tokens buy_lead").
        max_results: Maximum number of matching query blocks to return.

    Returns:
        Matching query blocks (ID, title, SQL snippet) from the knowledge base.
    """
    if not KNOWLEDGE_FILE.exists():
        return (
            "⚠️ `knowledge/redash_queries.md` not found. "
            "Add your exported Redash queries there first."
        )

    text = KNOWLEDGE_FILE.read_text(encoding="utf-8")

    # Split into blocks by "## [<id>]" headings
    blocks = re.split(r"(?=^## \[)", text, flags=re.MULTILINE)

    terms = [t.strip().lower() for t in re.split(r"[,\s]+", keywords) if t.strip()]

    hits = []
    for block in blocks:
        block_lower = block.lower()
        if any(t in block_lower for t in terms):
            hits.append(block.strip())

    if not hits:
        return (
            f"No queries found matching: **{keywords}**\n\n"
            "Tip: Try broader terms (table names, metric names, column names)."
        )

    hits = hits[:max_results]
    result = f"Found **{len(hits)}** matching query block(s) for `{keywords}`:\n\n---\n\n"
    result += "\n\n---\n\n".join(hits)
    return result


# ---------------------------------------------------------------------------
# Tool 3 — get_memory_notes
# ---------------------------------------------------------------------------
@mcp.tool()
def get_memory_notes(section: str = "") -> str:
    """
    Return the agent's memory_notes.md — metric definitions, city logic,
    time-period abbreviations (MTD, STLM, M-1, etc.), and query conventions.

    Args:
        section: Optional heading keyword to filter to a specific section
                 (e.g. "City Grouping", "Price Field", "Delivery").
                 Leave blank to return the full file.

    Returns:
        The relevant section(s) of memory_notes.md as Markdown.
    """
    if not MEMORY_FILE.exists():
        return "⚠️ `memory_notes.md` not found in the repo root."

    text = MEMORY_FILE.read_text(encoding="utf-8")

    if not section.strip():
        return text

    # Split by ## headings and filter
    sections = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    keyword = section.strip().lower()
    matches = [s for s in sections if keyword in s.lower()]

    if not matches:
        return (
            f"No section matching `{section}` found in memory_notes.md.\n\n"
            "Available headings:\n"
            + "\n".join(
                f"- {line}"
                for line in text.splitlines()
                if line.startswith("## ")
            )
        )

    return "\n\n".join(matches)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Redash Doris MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport type (stdio for Claude Desktop/Code, sse for remote)",
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for SSE transport"
    )
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run(transport="stdio")
