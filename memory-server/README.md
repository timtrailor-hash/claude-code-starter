# Memory server

Two-tier search over your Claude Code session transcripts.

- **Semantic tier**: Chroma Database (ChromaDB) with local Open Neural Network Exchange (ONNX) embeddings. No external Application Programming Interface (API) key required.
- **Keyword tier**: Structured Query Language (SQL) Lite Full-Text Search version 5 (FTS5) for exact-match queries.

Exposes five tools via the Model Context Protocol (MCP):

- `search_memory` — semantic search; returns top-N chunks by vector similarity.
- `search_exact` — keyword search over FTS5; supports boolean operators.
- `index_new` — index any new transcripts since the last run.
- `index_all` — reindex from scratch (use sparingly; minutes on large histories).
- `stats` — index size, last-index timestamp, chunk count.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

Edit the constants at the top of `memory_server.py`:

- `PROJECTS_ROOT`: directory under `~/.claude/projects/` whose JavaScript Object Notation Lines (JSONL) transcripts you want indexed. Usually one specific project; set more than one if you want a shared index.
- `DB_PATH`: where the ChromaDB and FTS5 files live on disk. Default: `./memory_server_data/` relative to the script.

The server reads one JSONL file per session. Each session is split into ~1,000-token chunks with metadata for date, topic, role.

## Run

Normally this is launched by Claude Code as a stdio Model Context Protocol server, not manually. The `settings.json` entry:

```json
"memory": {
  "type": "stdio",
  "command": "/opt/homebrew/bin/python3.11",
  "args": ["<PATH_TO>/memory-server/memory_server.py"]
}
```

For one-off manual testing:

```bash
source .venv/bin/activate
python3 memory_server.py --test
```

## Schedule indexing

The server indexes lazily on first query. For busy setups, schedule a periodic indexer via launchd:

```xml
<!-- Example LaunchAgent: indexes once an hour -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.example.memory-indexer</string>
    <key>ProgramArguments</key>
    <array>
      <string>/opt/homebrew/bin/python3.11</string>
      <string>/path/to/memory-server/memory_server.py</string>
      <string>--index-new</string>
    </array>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key><string>/tmp/memory-indexer.log</string>
    <key>StandardErrorPath</key><string>/tmp/memory-indexer.log</string>
</dict>
</plist>
```

## Known limits

- Semantic search uses a small local embedding model (good enough for personal use; not state-of-the-art). Upgrade by swapping the embedder in `memory_server.py` if you need it.
- FTS5 is exact-match with boolean operators. For fuzzy keyword match you would need to tokenise differently.
- Cross-session context (which session was contemporaneous with which) is preserved via timestamps but not exposed as a tool. Query manually by date if needed.
