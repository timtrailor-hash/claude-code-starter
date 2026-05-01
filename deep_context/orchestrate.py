"""Orchestrator for /deep-context v3 — plans fan-out to respect a quota budget.

Problem: 20 parallel Opus agents × 750K tokens = 15M tokens in a single burst,
which exhausts the Max 5-hour rolling quota. The orchestrator breaks the work
into waves so the quota window can breathe.

Public API:
  plan(n_shards, concurrency, models_per_wave, quota_soft_limit_tokens) → Plan

Used by the /deep-context skill: call `plan()`, dispatch wave by wave, wait
between waves if needed.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Wave:
    index: int
    session_shard_ids: list[int]  # e.g. [0, 1, 2, 3, 4] for first wave of 5
    includes_topics: bool = False
    includes_code: bool = False
    rough_tokens: int = 0


@dataclass
class Plan:
    total_shards: int
    concurrency: int
    model: str  # "opus" | "sonnet"
    rough_tokens_per_shard: int
    waves: list[Wave] = field(default_factory=list)

    @property
    def total_rough_tokens(self) -> int:
        return sum(w.rough_tokens for w in self.waves)

    @property
    def wave_count(self) -> int:
        return len(self.waves)


def plan(n_shards: int,
         concurrency: int = 5,
         model: str = "opus",
         rough_tokens_per_shard: int = 750_000,
         include_topics: bool = True,
         include_code: bool = True) -> Plan:
    """Build a wave-by-wave execution plan.

    - Sessions shards are split into waves of size `concurrency`.
    - Topics and code agents go in the last wave (they're smaller).
    """
    p = Plan(
        total_shards=n_shards,
        concurrency=concurrency,
        model=model,
        rough_tokens_per_shard=rough_tokens_per_shard,
    )
    shard_ids = list(range(n_shards))
    wave_idx = 0
    for i in range(0, n_shards, concurrency):
        wave_shards = shard_ids[i : i + concurrency]
        is_last = i + concurrency >= n_shards
        p.waves.append(Wave(
            index=wave_idx,
            session_shard_ids=wave_shards,
            includes_topics=is_last and include_topics,
            includes_code=is_last and include_code,
            rough_tokens=len(wave_shards) * rough_tokens_per_shard +
                         (100_000 if is_last and include_topics else 0) +
                         (100_000 if is_last and include_code else 0),
        ))
        wave_idx += 1
    return p


# --- Budget helpers ---

MAX_5H_WINDOW_TOKENS_CONSERVATIVE = 10_000_000   # conservative Opus-equivalent
MAX_5H_WINDOW_TOKENS_AGGRESSIVE = 20_000_000     # if Tim is willing to burn quota


def concurrency_for_budget(budget_tokens: int, rough_tokens_per_shard: int = 750_000) -> int:
    """How many agents can we safely burst per wave given a soft token budget?"""
    return max(1, budget_tokens // rough_tokens_per_shard)


def main():
    ap = argparse.ArgumentParser(prog="dc-plan")
    ap.add_argument("--n-shards", type=int, default=20)
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--model", default="opus")
    ap.add_argument("--budget-tokens", type=int, default=0,
                    help="If >0, overrides --concurrency using the token budget")
    args = ap.parse_args()

    concurrency = args.concurrency
    if args.budget_tokens:
        concurrency = concurrency_for_budget(args.budget_tokens)

    p = plan(n_shards=args.n_shards, concurrency=concurrency, model=args.model)
    print(json.dumps({
        "total_shards": p.total_shards,
        "concurrency_per_wave": p.concurrency,
        "model": p.model,
        "wave_count": p.wave_count,
        "waves": [
            {"index": w.index, "shard_ids": w.session_shard_ids,
             "topics": w.includes_topics, "code": w.includes_code,
             "rough_tokens": w.rough_tokens}
            for w in p.waves
        ],
        "total_rough_tokens": p.total_rough_tokens,
    }, indent=2))


if __name__ == "__main__":
    main()
