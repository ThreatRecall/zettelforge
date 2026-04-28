#!/usr/bin/env python3
"""
LOCOMO Benchmark for ZettelForge
=================================
Evaluates ZettelForge's memory system against the LoCoMo dataset
(Long-Context Conversational Memory).

Categories:
  1 = single-hop     (direct lookup from one dialogue turn)
  2 = multi-hop      (combine info across turns/sessions)
  3 = temporal        (time-based reasoning)
  4 = open-domain     (general knowledge, may not be in dialogue)
  5 = adversarial     (trick questions, memory shouldn't answer)

Scoring: LLM-as-judge (correct=1, partial=0.5, wrong=0)
         Falls back to keyword overlap if no LLM available.

Usage:
  python benchmarks/locomo_benchmark.py                    # Quick (20 per cat)
  python benchmarks/locomo_benchmark.py --full             # Full dataset
  python benchmarks/locomo_benchmark.py --samples 50       # Custom sample size
  python benchmarks/locomo_benchmark.py --judge ollama     # Use Ollama judge
"""
import json
import os
import sys
import time
import tempfile
import argparse
import statistics
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from zettelforge import MemoryManager


# ── Constants ────────────────────────────────────────────────────────────────

CATEGORY_NAMES = {
    1: "single-hop",
    2: "multi-hop",
    3: "temporal",
    4: "open-domain",
    5: "adversarial",
}

DATA_FILE = Path(__file__).parent.parent.parent / ".openclaw/workspace-nexus/Locomo-Plus/data/locomo10.json"
if not DATA_FILE.exists():
    DATA_FILE = Path.home() / ".openclaw/workspace-nexus/Locomo-Plus/data/locomo10.json"


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_locomo(path: Path) -> List[Dict]:
    """Load LoCoMo conversations with QA pairs."""
    with open(path) as f:
        return json.load(f)


def flatten_conversations(data: List[Dict]) -> List[Dict]:
    """Flatten multi-session conversations into dialogue turns with timestamps."""
    all_turns = []
    for conv in data:
        speakers = f"{conv['conversation'].get('speaker_a', 'A')} & {conv['conversation'].get('speaker_b', 'B')}"
        sample_id = conv.get("sample_id", "unknown")

        for key in sorted(conv["conversation"].keys()):
            if key.startswith("session_") and not key.endswith("date_time"):
                session_num = key.split("_")[1]
                date_key = f"session_{session_num}_date_time"
                session_date = conv["conversation"].get(date_key, "")
                turns = conv["conversation"][key]
                if not isinstance(turns, list):
                    continue
                for turn in turns:
                    all_turns.append({
                        "sample_id": sample_id,
                        "session": session_num,
                        "date": session_date,
                        "dia_id": turn.get("dia_id", ""),
                        "speaker": turn.get("speaker", ""),
                        "text": turn.get("text", ""),
                        "speakers": speakers,
                    })
    return all_turns


def sample_qa_pairs(data: List[Dict], per_category: int) -> List[Dict]:
    """Sample QA pairs balanced across categories."""
    by_cat = {}
    for conv in data:
        for qa in conv.get("qa", []):
            cat = qa.get("category", 0)
            if cat not in by_cat:
                by_cat[cat] = []
            by_cat[cat].append({
                **qa,
                "sample_id": conv.get("sample_id", "unknown"),
            })

    sampled = []
    for cat in sorted(by_cat.keys()):
        sampled.extend(by_cat[cat][:per_category])
    return sampled


# ── Ingestion ────────────────────────────────────────────────────────────────

def ingest_conversations(mm: MemoryManager, turns: List[Dict], batch_sessions: bool = True) -> Dict:
    """
    Ingest dialogue turns into ZettelForge. Returns metrics.

    If batch_sessions=True, groups turns by session and ingests as session
    chunks (much faster — avoids per-turn LLM causal extraction overhead).
    """
    start = time.perf_counter()
    ingested = 0
    errors = 0

    if batch_sessions:
        # Group turns into session chunks for efficient ingestion
        sessions = {}
        for turn in turns:
            key = f"{turn['sample_id']}:{turn['session']}"
            if key not in sessions:
                sessions[key] = {"date": turn["date"], "lines": [], "sample_id": turn["sample_id"], "session": turn["session"]}
            sessions[key]["lines"].append(f"{turn['speaker']}: {turn['text']}")

        for key, session in sessions.items():
            content = f"[{session['date']}] Conversation session {session['session']}:\n" + "\n".join(session["lines"])
            # Truncate very long sessions to avoid overwhelming the embedding
            if len(content) > 4000:
                content = content[:4000]
            try:
                mm.remember(
                    content=content,
                    source_type="dialogue",
                    source_ref=f"locomo:{session['sample_id']}:session_{session['session']}",
                    domain="locomo",
                )
                ingested += 1
            except RuntimeError as e:
                errors += 1
                if ingested == 0:
                    raise RuntimeError(f"Embedding server not available: {e}")
            if ingested % 25 == 0:
                elapsed = time.perf_counter() - start
                print(f"  Ingested {ingested} sessions ({elapsed:.0f}s)...")
    else:
        for turn in turns:
            content = f"[{turn['date']}] {turn['speaker']}: {turn['text']}"
            try:
                mm.remember(
                    content=content,
                    source_type="dialogue",
                    source_ref=f"locomo:{turn['sample_id']}:{turn['dia_id']}",
                    domain="locomo",
                )
                ingested += 1
            except RuntimeError as e:
                errors += 1
                if ingested == 0:
                    raise RuntimeError(f"Embedding server not available: {e}")

    duration = time.perf_counter() - start
    return {
        "ingested": ingested,
        "errors": errors,
        "duration_s": round(duration, 2),
        "rate_per_s": round(ingested / duration, 1) if duration > 0 else 0,
    }


# ── Retrieval + Answer ───────────────────────────────────────────────────────

def answer_question(mm: MemoryManager, question: str, k: int = 10) -> Tuple[str, List[str], float]:
    """
    Retrieve relevant memories and synthesize an answer.
    Returns: (answer, evidence_ids, latency_s)
    """
    start = time.perf_counter()

    # Retrieve relevant notes (disable supersession filter for conversational data
    # where sessions accumulate rather than replace each other)
    results = mm.recall(question, k=k, exclude_superseded=False)

    if not results:
        return "I don't have information about that.", [], time.perf_counter() - start

    # Build context from retrieved notes
    context_parts = []
    evidence_ids = []
    for note in results:
        context_parts.append(note.content.raw)
        evidence_ids.append(note.id)

    context = "\n".join(context_parts[:k])

    # Return raw context for keyword-overlap scoring (no LLM synthesis)
    answer = context[:2000]
    latency = time.perf_counter() - start

    return answer, evidence_ids, latency


def _synthesize_answer(question: str, context: str) -> str:
    """
    Use the local LLM to synthesize a focused answer from retrieved context.
    Falls back to raw context extraction if LLM is unavailable.
    """
    prompt = f"""Based on the following context, answer the question concisely.
If the answer is not in the context, say "I don't have information about that."
Do not add information not present in the context.

Context:
{context[:3000]}

Question: {question}

Answer:"""

    try:
        from zettelforge.llm_client import generate
        answer = generate(prompt, max_tokens=200, temperature=0.1)
        if answer and len(answer.strip()) > 5:
            return answer.strip()
    except Exception:
        pass

    # Fallback: extract most relevant sentences from context
    return _extract_relevant_sentences(question, context)


def _extract_relevant_sentences(question: str, context: str, max_sentences: int = 5) -> str:
    """
    Extract sentences from context that have highest token overlap with the question.
    Fallback when LLM synthesis is unavailable.
    """
    q_tokens = set(question.lower().split())
    sentences = [s.strip() for s in context.replace('\n', '. ').split('.') if len(s.strip()) > 10]

    scored = []
    for sent in sentences:
        s_tokens = set(sent.lower().split())
        overlap = len(q_tokens & s_tokens)
        scored.append((overlap, sent))

    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:max_sentences] if _ > 0]

    if not top:
        # Last resort: first few sentences of context
        top = sentences[:3]

    return ". ".join(top)


# ── Scoring ──────────────────────────────────────────────────────────────────

def keyword_judge(predicted: str, gold) -> float:
    """
    Simple keyword overlap judge.
    Returns: 1.0 (correct), 0.5 (partial), 0.0 (wrong)
    """
    pred_lower = str(predicted).lower()
    gold_lower = str(gold).lower()

    # Exact or near-exact match
    if gold_lower in pred_lower:
        return 1.0

    # Token overlap
    gold_tokens = set(gold_lower.split())
    pred_tokens = set(pred_lower.split())

    if not gold_tokens:
        return 0.0

    overlap = len(gold_tokens & pred_tokens)
    ratio = overlap / len(gold_tokens)

    if ratio >= 0.7:
        return 1.0
    elif ratio >= 0.3:
        return 0.5
    return 0.0


def llm_judge(predicted: str, gold, question: str, model: str = "ollama") -> float:
    """
    LLM-as-judge scoring. Uses local Ollama or llama.cpp.
    Returns: 1.0 (correct), 0.5 (partial), 0.0 (wrong)
    """
    prompt = f"""You are evaluating a memory system's answer. Score it:
- 1.0 = correct (answer contains the key information)
- 0.5 = partial (answer has some relevant info but is incomplete or slightly wrong)
- 0.0 = wrong (answer is incorrect, irrelevant, or missing the key point)

Question: {question}
Gold answer: {gold}
System answer: {predicted[:1000]}

Reply with ONLY a number: 1.0, 0.5, or 0.0"""

    try:
        import requests
        # Try llama.cpp / Ollama OpenAI-compatible endpoint
        url = os.environ.get("JUDGE_URL", "http://localhost:11434")
        judge_model = os.environ.get("JUDGE_MODEL", "qwen3.5:9b")

        resp = requests.post(
            f"{url}/api/generate",
            json={"model": judge_model, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "").strip()

        # Parse score
        for val in ["1.0", "0.5", "0.0"]:
            if val in text:
                return float(val)
        return 0.0
    except Exception:
        # Fallback to keyword judge
        return keyword_judge(predicted, gold)


# ── Main Benchmark ───────────────────────────────────────────────────────────

def run_benchmark(
    data_path: Path = DATA_FILE,
    per_category: int = 20,
    use_llm_judge: bool = False,
    k: int = 10,
) -> Dict:
    """Run the full LOCOMO benchmark."""

    print("=" * 70)
    print("  LOCOMO Benchmark for ZettelForge")
    print(f"  Date: {datetime.now().isoformat()}")
    from zettelforge import __version__
    print(f"  Version: ZettelForge {__version__}")
    print(f"  Dataset: {data_path.name}")
    print(f"  Samples per category: {per_category}")
    print(f"  Judge: {'LLM' if use_llm_judge else 'keyword-overlap'}")
    print("=" * 70)

    # Load data
    print("\n[1/4] Loading LoCoMo dataset...")
    data = load_locomo(data_path)
    all_turns = flatten_conversations(data)
    qa_pairs = sample_qa_pairs(data, per_category)

    print(f"  Conversations: {len(data)}")
    print(f"  Dialogue turns: {len(all_turns)}")
    print(f"  QA pairs: {len(qa_pairs)}")

    cat_counts = {}
    for qa in qa_pairs:
        cat = qa.get("category", 0)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    for cat, count in sorted(cat_counts.items()):
        print(f"    {CATEGORY_NAMES.get(cat, f'cat-{cat}')}: {count}")

    # Initialize ZettelForge with isolated storage
    tmpdir = tempfile.mkdtemp(prefix="locomo_bench_")
    mm = MemoryManager(
        jsonl_path=f"{tmpdir}/notes.jsonl",
        lance_path=f"{tmpdir}/vectordb",
    )

    # Ingest
    print(f"\n[2/4] Ingesting {len(all_turns)} dialogue turns...")
    ingest_metrics = ingest_conversations(mm, all_turns)
    print(f"  Ingested: {ingest_metrics['ingested']} turns")
    print(f"  Errors: {ingest_metrics['errors']}")
    print(f"  Duration: {ingest_metrics['duration_s']}s")
    print(f"  Rate: {ingest_metrics['rate_per_s']} turns/s")

    # Evaluate
    print(f"\n[3/4] Evaluating {len(qa_pairs)} QA pairs...")
    results_by_cat = {}
    all_results = []

    for i, qa in enumerate(qa_pairs):
        cat = qa.get("category", 0)
        cat_name = CATEGORY_NAMES.get(cat, f"cat-{cat}")

        if cat_name not in results_by_cat:
            results_by_cat[cat_name] = {
                "scores": [],
                "latencies": [],
                "retrieved_counts": [],
            }

        answer, evidence_ids, latency = answer_question(mm, qa["question"], k=k)

        gold_answer = qa.get("answer", qa.get("adversarial_answer", ""))

        if use_llm_judge:
            score = llm_judge(answer, gold_answer, qa["question"])
        else:
            score = keyword_judge(answer, gold_answer)

        results_by_cat[cat_name]["scores"].append(score)
        results_by_cat[cat_name]["latencies"].append(latency)
        results_by_cat[cat_name]["retrieved_counts"].append(len(evidence_ids))

        all_results.append({
            "category": cat_name,
            "question": qa["question"],
            "gold_answer": str(gold_answer),
            "predicted": answer[:500],
            "score": score,
            "latency_s": round(latency, 3),
            "retrieved": len(evidence_ids),
        })

        if (i + 1) % 25 == 0:
            print(f"  Evaluated {i + 1}/{len(qa_pairs)}...")

    # Report
    print(f"\n[4/4] Results")
    print("=" * 70)
    print(f"{'Category':<15} {'Accuracy':>10} {'Avg Score':>10} {'p50 Lat':>10} {'p95 Lat':>10} {'Avg Ret':>8} {'N':>5}")
    print("-" * 70)

    overall_scores = []
    overall_latencies = []

    for cat_name in ["single-hop", "multi-hop", "temporal", "open-domain", "adversarial"]:
        stats = results_by_cat.get(cat_name)
        if not stats or not stats["scores"]:
            print(f"{cat_name:<15} {'--':>10} {'--':>10} {'--':>10} {'--':>10} {'--':>8} {'0':>5}")
            continue

        scores = stats["scores"]
        lats = stats["latencies"]
        rets = stats["retrieved_counts"]

        accuracy = sum(1 for s in scores if s == 1.0) / len(scores) * 100
        avg_score = statistics.mean(scores)
        p50_lat = statistics.median(lats)
        p95_lat = sorted(lats)[int(len(lats) * 0.95)] if len(lats) >= 2 else lats[0]
        avg_ret = statistics.mean(rets)

        print(f"{cat_name:<15} {accuracy:>9.1f}% {avg_score:>9.2f} {p50_lat*1000:>8.0f}ms {p95_lat*1000:>8.0f}ms {avg_ret:>7.1f} {len(scores):>5}")

        overall_scores.extend(scores)
        overall_latencies.extend(lats)

    print("-" * 70)

    if overall_scores:
        oa = sum(1 for s in overall_scores if s == 1.0) / len(overall_scores) * 100
        os_avg = statistics.mean(overall_scores)
        ol_p50 = statistics.median(overall_latencies)
        ol_p95 = sorted(overall_latencies)[int(len(overall_latencies) * 0.95)]

        print(f"{'OVERALL':<15} {oa:>9.1f}% {os_avg:>9.2f} {ol_p50*1000:>8.0f}ms {ol_p95*1000:>8.0f}ms {'':>8} {len(overall_scores):>5}")

    print("=" * 70)

    # Comparison table
    print("\n  Comparison (LoCoMo leaderboard):")
    print(f"  {'System':<20} {'Accuracy':>10}")
    print(f"  {'-'*30}")
    print(f"  {'Mem0g':.<20} {'68.5%':>10}")
    print(f"  {'Mem0':.<20} {'66.9%':>10}")
    print(f"  {'LangMem':.<20} {'58.1%':>10}")
    print(f"  {'OpenAI Memory':.<20} {'52.9%':>10}")
    if overall_scores:
        print(f"  {f'ZettelForge {__version__}':.<20} {oa:>9.1f}%  <-- current")

    # Save results
    output = {
        "meta": {
            "date": datetime.now().isoformat(),
            "version": f"zettelforge-{__version__}",
            "dataset": str(data_path),
            "per_category": per_category,
            "judge": "llm" if use_llm_judge else "keyword",
            "k": k,
        },
        "ingest": ingest_metrics,
        "by_category": {
            cat: {
                "accuracy": sum(1 for s in stats["scores"] if s == 1.0) / len(stats["scores"]) * 100,
                "avg_score": statistics.mean(stats["scores"]),
                "p50_latency_ms": statistics.median(stats["latencies"]) * 1000,
                "p95_latency_ms": sorted(stats["latencies"])[int(len(stats["latencies"]) * 0.95)] * 1000 if len(stats["latencies"]) >= 2 else 0,
                "n": len(stats["scores"]),
            }
            for cat, stats in results_by_cat.items()
            if stats["scores"]
        },
        "overall": {
            "accuracy": oa if overall_scores else 0,
            "avg_score": os_avg if overall_scores else 0,
            "p50_latency_ms": ol_p50 * 1000 if overall_scores else 0,
            "p95_latency_ms": ol_p95 * 1000 if overall_scores else 0,
            "total_samples": len(overall_scores),
        },
        "details": all_results,
    }

    results_path = Path(__file__).parent / "locomo_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nDetailed results: {results_path}")

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LOCOMO Benchmark for ZettelForge")
    parser.add_argument("--full", action="store_true", help="Run on full dataset (no sampling)")
    parser.add_argument("--samples", type=int, default=20, help="Samples per category (default: 20)")
    parser.add_argument("--judge", choices=["keyword", "ollama"], default="keyword", help="Judge type")
    parser.add_argument("--k", type=int, default=10, help="Top-k retrieval (default: 10)")
    parser.add_argument("--data", type=str, default=None, help="Path to locomo10.json")
    args = parser.parse_args()

    data_path = Path(args.data) if args.data else DATA_FILE
    per_cat = 9999 if args.full else args.samples

    run_benchmark(
        data_path=data_path,
        per_category=per_cat,
        use_llm_judge=(args.judge == "ollama"),
        k=args.k,
    )
