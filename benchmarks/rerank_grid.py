#!/usr/bin/env python3
"""Measure rerank policy variants on the CTI suite: accuracy vs p50 latency.

Grid: doc_chars x max_candidates plus rerank-off. Run on an idle machine;
results pick the config.default.yaml tuned values (zero accuracy loss rule).

Usage:
  python benchmarks/rerank_grid.py
"""
import os

os.environ.setdefault('ZETTELFORGE_ENRICHMENT_ENABLED', 'false')

from cti_retrieval_benchmark import run_strategy

from zettelforge.config import get_config


def main() -> None:
    cfg = get_config().retrieval
    variants = [
        ('off', False, 50, 512),
        ('512c-50n (current)', True, 50, 512),
        ('512c-16n', True, 16, 512),
        ('384c-16n', True, 16, 384),
        ('256c-16n', True, 16, 256),
        ('256c-8n', True, 8, 256),
        ('128c-8n', True, 8, 128),
    ]
    print(f'{"variant":<22} {"accuracy":>9} {"avg":>6} {"p50ms":>7} {"p95ms":>7}')
    for name, enabled, max_cand, chars in variants:
        cfg.rerank_enabled = enabled
        cfg.rerank_max_candidates = max_cand
        cfg.rerank_doc_chars = chars
        r = run_strategy('full_session')
        print(
            f'{name:<22} {r["accuracy"]:>8}% {r["avg_score"]:>6} '
            f'{r["p50_latency_ms"]:>7.0f} {r["p95_latency_ms"]:>7.0f}'
        )


if __name__ == '__main__':
    main()
