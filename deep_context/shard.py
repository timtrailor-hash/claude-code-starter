"""Shard helper — partition prestripped session files into byte-balanced buckets.

v3 fan-out runs N parallel agents, each reading a shard of the prestripped
corpus. Balancing by total bytes (not file count) prevents one shard from
containing a single huge session while another has dozens of tiny ones.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PRESTRIPPED_ROOT = Path.home() / "code" / "memory_server_data" / "prestripped"


def partition_balanced(files_with_sizes: list[tuple[Path, int]], n_shards: int) -> list[list[Path]]:
    """Greedy balanced partition: sort by size desc, then place each into the currently smallest shard."""
    files_with_sizes = sorted(files_with_sizes, key=lambda x: -x[1])
    shards: list[list[Path]] = [[] for _ in range(n_shards)]
    sizes: list[int] = [0] * n_shards
    for path, size in files_with_sizes:
        i = min(range(n_shards), key=lambda k: sizes[k])
        shards[i].append(path)
        sizes[i] += size
    return shards


def compute_shards(n_shards: int = 20, root: Path | None = None) -> list[list[Path]]:
    root = root or PRESTRIPPED_ROOT
    files = list(root.rglob("*.txt"))
    if not files:
        return [[] for _ in range(n_shards)]
    fws = [(f, f.stat().st_size) for f in files]
    return partition_balanced(fws, n_shards)


def write_shard_files(shards: list[list[Path]], out_dir: Path) -> list[Path]:
    """Write each shard as a newline-separated list of prestripped file paths.

    Fan-out agents read the manifest file and then read each listed transcript.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests: list[Path] = []
    for i, shard in enumerate(shards):
        m = out_dir / f"shard_{i:02d}.txt"
        m.write_text("\n".join(str(p) for p in shard) + "\n")
        manifests.append(m)
    return manifests


def run(args):
    shards = compute_shards(n_shards=args.n, root=Path(args.root) if args.root else None)
    out_dir = Path(args.out)
    manifests = write_shard_files(shards, out_dir)
    summary = []
    for i, (m, shard) in enumerate(zip(manifests, shards)):
        total = sum(p.stat().st_size for p in shard)
        summary.append({"shard": i, "manifest": str(m), "files": len(shard), "bytes": total, "rough_tokens": total // 4})
    print(json.dumps({"out_dir": str(out_dir), "shards": summary}, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="dc-shard")
    p.add_argument("--n", type=int, default=20, help="number of shards")
    p.add_argument("--root", default="", help="prestripped root (default: ~/code/memory_server_data/prestripped)")
    p.add_argument("--out", required=True, help="output directory for shard manifests")
    args = p.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
