"""Deep-context pipeline.

Modules:
  schema    — compressed-session JSON-schema + validator
  prestrip  — JSONL → compact prompt-ready representation
  classify  — route sonnet vs opus (7-factor heuristic)
  compress  — call Claude CLI to produce a compressed-session markdown file
  index     — unified index (Chroma + FTS5) for compressed sessions
  filter    — pre-filter: brief → candidate session IDs
  aggregate — fan-out outputs → context.md
"""

from . import schema, prestrip, classify, compress, index, filter, aggregate  # noqa: F401
