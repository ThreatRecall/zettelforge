#!/usr/bin/env python3
"""
CTIBench Benchmark Adapter for ZettelForge
============================================
Adapts CTIBench (NeurIPS 2024) tasks as retrieval benchmarks.

Tasks:
  CTI-ATE: ATT&CK Technique Extraction from threat descriptions
           Ingest descriptions -> query -> compare predicted technique IDs to ground truth
           Scoring: set-based Precision, Recall, F1

  CTI-TAA: Threat Actor Attribution from redacted reports
           Ingest redacted reports -> query "who is [PLACEHOLDER]?" -> compare to ground truth
           Scoring: exact match + alias match (case-insensitive)

Usage:
  python benchmarks/ctibench_benchmark.py                  # Run both tasks
  python benchmarks/ctibench_benchmark.py --task ate       # ATE only
  python benchmarks/ctibench_benchmark.py --task taa       # TAA only
  python benchmarks/ctibench_benchmark.py --samples 50     # Limit samples

Source: https://huggingface.co/datasets/AI4Sec/cti-bench
Paper: https://arxiv.org/abs/2406.07599 (NeurIPS 2024)
"""

import argparse
import json
import re
import statistics
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from zettelforge import MemoryManager, __version__

# -- ATT&CK Technique Loader --------------------------------------------------

_ATTACK_DIR = Path(__file__).parent

# All three ATT&CK matrices — enterprise, mobile, ICS
_ATTACK_FILES = [
    _ATTACK_DIR / "enterprise-attack.json",
    _ATTACK_DIR / "mobile-attack.json",
    _ATTACK_DIR / "ics-attack.json",
]


def _download_attack_files() -> None:
    """Download any missing ATT&CK matrix JSON files from MITRE."""
    import urllib.request

    base = "https://raw.githubusercontent.com/mitre/cti/master"
    for path in _ATTACK_FILES:
        if path.exists():
            continue
        matrix = path.stem  # e.g. "enterprise-attack"
        url = f"{base}/{matrix}/{matrix}.json"
        print(f"  Downloading {matrix}.json ...")
        urllib.request.urlretrieve(url, str(path))


def load_attack_techniques() -> List[Dict]:
    """
    Load MITRE ATT&CK techniques from all matrices (enterprise + mobile + ICS).

    Returns a list of dicts with keys: external_id, name, description.
    Sub-techniques (IDs containing a dot, e.g. T1071.001) are excluded
    per CTIBench scoring which normalises sub-techniques to their parent.
    """
    _download_attack_files()

    techniques = []
    seen_ids: set = set()
    for attack_json in _ATTACK_FILES:
        if not attack_json.exists():
            continue
        with open(attack_json) as f:
            data = json.load(f)
        for obj in data.get("objects", []):
            if obj.get("type") != "attack-pattern":
                continue
            if obj.get("x_mitre_deprecated", False) or obj.get("revoked", False):
                continue
            ext_id = None
            for ref in obj.get("external_references", []):
                if ref.get("source_name") in (
                    "mitre-attack",
                    "mitre-mobile-attack",
                    "mitre-ics-attack",
                ):
                    ext_id = ref.get("external_id", "")
                    break
            if not ext_id or "." in ext_id:
                continue
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            techniques.append(
                {
                    "external_id": ext_id,
                    "name": obj.get("name", ""),
                    "description": obj.get("description", ""),
                }
            )
    return techniques


def populate_attack_techniques(mm: MemoryManager, techniques: List[Dict]) -> int:
    """
    Ingest ATT&CK technique entries into a ZettelForge instance.

    Each note is formatted as:
        "<T-code> <name>: <description[:500]>"

    The T-code is embedded in the content so the existing
    extract_technique_ids() regex will find matches in retrieved results.

    Returns the number of techniques successfully ingested.
    """
    ingested = 0
    for tech in techniques:
        ext_id = tech["external_id"]
        name = tech["name"]
        desc = tech["description"][:500]
        content = f"{ext_id} {name}: {desc}"
        try:
            mm.remember(
                content=content,
                source_type="mitre_attack",
                source_ref=f"https://attack.mitre.org/techniques/{ext_id}/",
                domain="attack_techniques",
            )
            ingested += 1
        except Exception:
            pass
    return ingested


# -- Data Loading -------------------------------------------------------------


def load_ctibench_ate(max_samples: Optional[int] = None) -> List[Dict]:
    """Load CTI-ATE dataset from HuggingFace."""
    from datasets import load_dataset

    ds = load_dataset(
        "AI4Sec/cti-bench",
        data_files="cti-ate.tsv",
        split="train",
        delimiter="\t",
        quoting=3,  # QUOTE_NONE to handle embedded quotes
    )
    rows = []
    for i, row in enumerate(ds):
        if max_samples and i >= max_samples:
            break
        gt_raw = row.get("GT", "")
        # Parse comma-separated technique IDs
        gt_ids = set(t.strip() for t in gt_raw.split(",") if t.strip())
        if not gt_ids:
            continue
        rows.append(
            {
                "description": row.get("Description", ""),
                "platform": row.get("Platform", "Enterprise"),
                "ground_truth": gt_ids,
                "url": row.get("URL", ""),
            }
        )
    return rows


def load_ctibench_taa(max_samples: Optional[int] = None) -> List[Dict]:
    """Load CTI-TAA dataset from HuggingFace."""
    from datasets import load_dataset

    ds = load_dataset(
        "AI4Sec/cti-bench",
        data_files="cti-taa.tsv",
        split="train",
        delimiter="\t",
        quoting=3,
    )
    rows = []
    for i, row in enumerate(ds):
        if max_samples and i >= max_samples:
            break
        text = row.get("Text", "")
        if not text or "[PLACEHOLDER]" not in text:
            continue
        rows.append(
            {
                "text": text,
                "prompt": row.get("Prompt", ""),
                "url": row.get("URL", ""),
            }
        )
    return rows


def load_taa_ground_truth() -> Dict[int, str]:
    """
    Load TAA ground truth from the responses file.
    Returns {row_index: actor_name}.
    Falls back to extracting from URL if responses file unavailable.
    """
    try:
        from datasets import load_dataset

        ds = load_dataset(
            "AI4Sec/cti-bench",
            data_files="cti-taa.tsv",
            split="train",
            delimiter="\t",
            quoting=3,
        )
        # TAA ground truth is in a separate responses file in the GitHub repo
        # Since we may not have it, extract actor names from URLs as fallback
        gt = {}
        for i, row in enumerate(ds):
            url = row.get("URL", "")
            # Many CTI report URLs contain the actor name
            # This is a best-effort fallback
            gt[i] = url
        return gt
    except Exception:
        return {}


# -- Scoring -------------------------------------------------------------------


def score_ate(predicted_ids: Set[str], ground_truth: Set[str]) -> Dict:
    """Score ATT&CK Technique Extraction using set-based P/R/F1."""
    if not ground_truth:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    # Normalize: uppercase, strip whitespace
    pred = set(t.upper().strip() for t in predicted_ids if t.strip())
    gt = set(t.upper().strip() for t in ground_truth)

    if not pred:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    tp = len(pred & gt)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gt) if gt else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def score_taa(predicted: str, ground_truth: str) -> Dict:
    """Score Threat Actor Attribution using exact + fuzzy matching."""
    pred_lower = predicted.lower().strip()
    gt_lower = ground_truth.lower().strip()

    # Exact match
    if gt_lower in pred_lower or pred_lower in gt_lower:
        return {"score": 1.0, "match": "exact"}

    # Token overlap
    gt_tokens = set(gt_lower.split())
    pred_tokens = set(pred_lower.split())
    if gt_tokens and len(gt_tokens & pred_tokens) / len(gt_tokens) >= 0.5:
        return {"score": 0.5, "match": "partial"}

    return {"score": 0.0, "match": "none"}


# -- Extraction from Retrieved Context ----------------------------------------


def extract_technique_ids(text: str) -> Set[str]:
    """Extract MITRE ATT&CK technique IDs from retrieved context."""
    pattern = r"T\d{4}(?:\.\d{3})?"
    matches = re.findall(pattern, text)
    # Only keep main technique IDs (no sub-techniques) per CTIBench spec
    main_ids = set()
    for m in matches:
        if "." in m:
            main_ids.add(m.split(".")[0])
        else:
            main_ids.add(m)
    return main_ids


def extract_actor_name(text: str) -> str:
    """Extract most likely threat actor name from retrieved context."""
    # Look for common actor patterns
    patterns = [
        r"\b(APT\s*\d+)\b",
        r"\b(Lazarus(?:\s+Group)?)\b",
        r"\b(Sandworm)\b",
        r"\b(Fancy\s+Bear)\b",
        r"\b(Cozy\s+Bear)\b",
        r"\b(Volt\s+Typhoon)\b",
        r"\b(Turla)\b",
        r"\b(Kimsuky)\b",
        r"\b(Charming\s+Kitten)\b",
        r"\b(MuddyWater)\b",
        r"\b(OceanLotus)\b",
        r"\b(DarkHotel)\b",
        r"\b(Equation\s+Group)\b",
        r"\b(UNC\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    # Fallback: return first capitalized multi-word phrase
    phrases = re.findall(r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", text)
    if phrases:
        return phrases[0]

    return ""


# -- Benchmark Runner ----------------------------------------------------------


def run_ate_benchmark(max_samples: Optional[int] = None, k: int = 25) -> Dict:
    """Run CTI-ATE benchmark: ingest descriptions, retrieve, extract techniques."""
    print("\n" + "=" * 70)
    print("  CTI-ATE: ATT&CK Technique Extraction Benchmark")
    print("=" * 70)

    # Load data
    print("\n[1/4] Loading CTI-ATE dataset...")
    samples = load_ctibench_ate(max_samples)
    print(f"  Loaded {len(samples)} samples")

    # Build ZettelForge instance
    tmpdir = tempfile.mkdtemp(prefix="ctibench_ate_")
    mm = MemoryManager(
        jsonl_path=f"{tmpdir}/notes.jsonl",
        lance_path=f"{tmpdir}/vectordb",
    )

    # Pre-populate with ATT&CK technique entries so T-codes are retrievable
    print("\n[2/4] Pre-populating ATT&CK techniques into ZettelForge...")
    attack_techniques = load_attack_techniques()
    print(
        f"  Loaded {len(attack_techniques)} main techniques from ATT&CK matrices (enterprise + mobile + ICS)"
    )
    atk_start = time.perf_counter()
    atk_ingested = populate_attack_techniques(mm, attack_techniques)
    print(f"  Ingested {atk_ingested} technique entries in {time.perf_counter() - atk_start:.1f}s")

    # Ingest CTI descriptions into ZettelForge (provides retrieval context)
    print("\n[3/4] Ingesting CTI threat descriptions...")
    start = time.perf_counter()
    ingested = 0
    for sample in samples:
        try:
            mm.remember(
                content=sample["description"],
                source_type="threat_report",
                source_ref=sample["url"],
                domain="cti",
            )
            ingested += 1
        except Exception:
            if ingested == 0:
                raise
    ingest_duration = time.perf_counter() - start
    print(f"  Ingested {ingested} descriptions in {ingest_duration:.1f}s")

    # Evaluate — search attack_techniques domain only (not CTI descriptions)
    print(f"\n[4/4] Evaluating {len(samples)} samples...")
    results = []
    for i, sample in enumerate(samples):
        # Use raw description as query (not meta-question wrapper)
        # to stay in the same embedding space as technique descriptions
        query = sample["description"][:500]
        start_q = time.perf_counter()
        retrieved = mm.recall(query, k=k, domain="attack_techniques")
        latency = time.perf_counter() - start_q

        # Extract technique IDs from retrieved context
        context = " ".join(n.content.raw for n in retrieved)
        predicted_ids = extract_technique_ids(context)

        scores = score_ate(predicted_ids, sample["ground_truth"])
        results.append(
            {
                "precision": scores["precision"],
                "recall": scores["recall"],
                "f1": scores["f1"],
                "latency_s": latency,
                "predicted": sorted(predicted_ids),
                "ground_truth": sorted(sample["ground_truth"]),
                "retrieved_count": len(retrieved),
            }
        )

        if (i + 1) % 25 == 0:
            print(f"  Evaluated {i + 1}/{len(samples)}...")

    # Aggregate
    avg_precision = statistics.mean(r["precision"] for r in results)
    avg_recall = statistics.mean(r["recall"] for r in results)
    avg_f1 = statistics.mean(r["f1"] for r in results)
    p50_lat = statistics.median(r["latency_s"] for r in results)

    print("\n  Results:")
    print(f"    Precision: {avg_precision:.3f}")
    print(f"    Recall:    {avg_recall:.3f}")
    print(f"    F1:        {avg_f1:.3f}")
    print(f"    p50 Lat:   {p50_lat * 1000:.0f}ms")

    return {
        "task": "CTI-ATE",
        "n": len(results),
        "precision": round(avg_precision, 4),
        "recall": round(avg_recall, 4),
        "f1": round(avg_f1, 4),
        "p50_latency_ms": round(p50_lat * 1000, 1),
        "ingest_duration_s": round(ingest_duration, 1),
        "details": results,
    }


def run_taa_benchmark(max_samples: Optional[int] = None, k: int = 10) -> Dict:
    """Run CTI-TAA benchmark: ingest redacted reports, identify threat actors."""
    print("\n" + "=" * 70)
    print("  CTI-TAA: Threat Actor Attribution Benchmark")
    print("=" * 70)

    # Load data
    print("\n[1/3] Loading CTI-TAA dataset...")
    samples = load_ctibench_taa(max_samples)
    print(f"  Loaded {len(samples)} samples")

    if not samples:
        print("  WARNING: No TAA samples loaded. Skipping.")
        return {"task": "CTI-TAA", "n": 0, "accuracy": 0.0, "details": []}

    # Ingest reports into ZettelForge
    print("\n[2/3] Ingesting threat reports...")
    tmpdir = tempfile.mkdtemp(prefix="ctibench_taa_")
    mm = MemoryManager(
        jsonl_path=f"{tmpdir}/notes.jsonl",
        lance_path=f"{tmpdir}/vectordb",
    )

    start = time.perf_counter()
    ingested = 0
    for sample in samples:
        try:
            mm.remember(
                content=sample["text"][:1500],
                source_type="threat_report",
                source_ref=sample["url"],
                domain="cti",
            )
            ingested += 1
        except Exception:
            if ingested == 0:
                raise
    ingest_duration = time.perf_counter() - start
    print(f"  Ingested {ingested} reports in {ingest_duration:.1f}s")

    # Evaluate
    print(f"\n[3/3] Evaluating {len(samples)} samples...")
    results = []
    for i, sample in enumerate(samples):
        query = "Identify the threat actor referred to as [PLACEHOLDER] in the report"
        start_q = time.perf_counter()
        retrieved = mm.recall(query, k=k, domain="cti")
        latency = time.perf_counter() - start_q

        context = " ".join(n.content.raw for n in retrieved)
        predicted_actor = extract_actor_name(context)

        results.append(
            {
                "predicted": predicted_actor,
                "latency_s": latency,
                "retrieved_count": len(retrieved),
            }
        )

        if (i + 1) % 25 == 0:
            print(f"  Evaluated {i + 1}/{len(samples)}...")

    p50_lat = statistics.median(r["latency_s"] for r in results) if results else 0

    print("\n  Results:")
    print(f"    Samples:  {len(results)}")
    print(f"    p50 Lat:  {p50_lat * 1000:.0f}ms")
    print("    NOTE: TAA ground truth requires GitHub alias/related dicts for proper scoring.")
    print("          Predictions saved for manual review or future scoring.")

    return {
        "task": "CTI-TAA",
        "n": len(results),
        "p50_latency_ms": round(p50_lat * 1000, 1),
        "ingest_duration_s": round(ingest_duration, 1),
        "note": "Ground truth scoring requires alias_dict.pickle from CTIBench GitHub repo",
        "details": results,
    }


def run_benchmark(task: str = "both", max_samples: Optional[int] = None, k: int = 10) -> Dict:
    """Run CTIBench benchmarks."""
    print("=" * 70)
    print("  CTIBench Benchmark for ZettelForge")
    print(f"  Date: {datetime.now().isoformat()}")
    print(f"  Version: ZettelForge {__version__}")
    print("  Source: AI4Sec/cti-bench (NeurIPS 2024)")
    print(f"  Tasks: {task}")
    print(f"  Max samples: {max_samples or 'all'}")
    print("=" * 70)

    output = {
        "meta": {
            "date": datetime.now().isoformat(),
            "version": f"zettelforge-{__version__}",
            "source": "AI4Sec/cti-bench (NeurIPS 2024)",
            "k": k,
            "max_samples": max_samples,
        },
        "tasks": {},
    }

    if task in ("both", "ate"):
        output["tasks"]["CTI-ATE"] = run_ate_benchmark(max_samples, k)

    if task in ("both", "taa"):
        output["tasks"]["CTI-TAA"] = run_taa_benchmark(max_samples, k)

    # Save results
    results_path = Path(__file__).parent / "ctibench_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved: {results_path}")

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CTIBench Benchmark for ZettelForge")
    parser.add_argument("--task", choices=["ate", "taa", "both"], default="both")
    parser.add_argument("--samples", type=int, default=None, help="Max samples per task")
    parser.add_argument("--k", type=int, default=10, help="Top-k retrieval")
    args = parser.parse_args()

    run_benchmark(task=args.task, max_samples=args.samples, k=args.k)
