#!/usr/bin/env python3
"""
CTI Retrieval Benchmark — Tests ZettelForge on real CTI queries.

Unlike LOCOMO (conversational memory), this tests what ZettelForge
is actually built for: threat actor attribution, tool mapping,
CVE linkage, campaign tracking, and temporal intel queries.

Measures accuracy and latency for both chunking strategies:
  - full_session: store entire intel reports as single notes (current)
  - chunked_800: split reports into 800-char chunks on sentence boundaries

Usage:
  python benchmarks/cti_retrieval_benchmark.py
"""
import json
import os
import time
import tempfile
import statistics
from datetime import datetime
from typing import List, Dict, Tuple

os.environ["ZETTELFORGE_BACKEND"] = "jsonl"
# Deterministic ingestion: no background LLM enrichment during benchmarks.
os.environ.setdefault("ZETTELFORGE_ENRICHMENT_ENABLED", "false")

from zettelforge import MemoryManager

# ── CTI Corpus ────────────────────────────────────────────────────────────────
# Real-world-style threat intelligence reports

CTI_REPORTS = [
    {
        "id": "report_001",
        "content": """APT28 (also known as Fancy Bear, Sofacy, or Strontium) is a Russian state-sponsored threat actor attributed to the GRU (Main Intelligence Directorate). In 2024, APT28 shifted its primary initial access vector from spearphishing emails to exploitation of edge network devices, particularly VPN appliances and firewalls. The group has been observed using Cobalt Strike beacons for command and control, and deploying the DROPBEAR backdoor for persistent access. APT28 has targeted NATO member states, defense contractors, and energy sector organizations. The group exploited CVE-2024-1111 in Fortinet FortiGate devices for initial access in multiple campaigns during Q1 2024. CERT-UA attributed the SedUploader malware to APT28 operations in Ukraine.""",
    },
    {
        "id": "report_002",
        "content": """Lazarus Group (also known as Hidden Cobra, Zinc, or Diamond Sleet) is a North Korean state-sponsored threat actor attributed to the Reconnaissance General Bureau. The group is known for financially motivated attacks targeting cryptocurrency exchanges and SWIFT banking systems. In 2024, Lazarus Group deployed the Manuscrypt RAT and the TraderTraitor malware in attacks against DeFi platforms. The group exploited CVE-2024-21887 in Ivanti Connect Secure VPN for initial access. Lazarus has been linked to the $600M Ronin Bridge cryptocurrency theft in 2022 and continues to generate revenue for the DPRK regime through cyber operations.""",
    },
    {
        "id": "report_003",
        "content": """Volt Typhoon is a Chinese state-sponsored threat actor that has compromised critical infrastructure in the United States, including water utilities, telecommunications, and energy sector organizations. The group uses living-off-the-land (LOTL) techniques, relying on built-in Windows tools like PowerShell, WMI, and netsh rather than deploying custom malware. Volt Typhoon gains initial access through exploitation of internet-facing devices, particularly Fortinet FortiGuard, Ivanti Connect Secure, and SOHO routers. The group has been pre-positioning in critical infrastructure networks for potential future disruption. Microsoft and CISA issued joint advisories about Volt Typhoon activity in May 2023 and February 2024.""",
    },
    {
        "id": "report_004",
        "content": """MuddyWater (also known as Mercury, Mango Sandstorm, or Static Kitten) is an Iranian state-sponsored threat actor associated with the Ministry of Intelligence and Security (MOIS). The group primarily targets Middle Eastern organizations in the telecommunications, government, and defense sectors. MuddyWater uses the PowGoop loader, the Small Sieve backdoor, and custom PowerShell scripts for post-exploitation. In 2024, the group deployed a new variant of the Dindoor backdoor linked to CVE-2026-3055 in Microsoft Exchange. MuddyWater has been observed conducting espionage operations and sharing infrastructure with other Iranian groups including OilRig and Charming Kitten.""",
    },
    {
        "id": "report_005",
        "content": """Scattered Spider (also known as UNC3944 or Octo Tempest) is a financially motivated threat group known for social engineering attacks against large enterprises. The group specializes in SIM swapping, MFA fatigue attacks, and help desk social engineering to gain initial access. Scattered Spider has targeted major casino and hospitality companies including MGM Resorts and Caesars Entertainment. The group deploys ransomware (including ALPHV/BlackCat) after gaining access, and has been observed exfiltrating data for double extortion. Members of Scattered Spider are primarily English-speaking individuals, distinguishing them from most ransomware groups which are Russian-speaking.""",
    },
    {
        "id": "report_006",
        "content": """CVE-2024-3094 is a critical supply chain backdoor discovered in XZ Utils versions 5.6.0 and 5.6.1 in March 2024. The backdoor was inserted by a maintainer account (Jia Tan) that had been contributing to the project for over two years. The vulnerability allows remote code execution through the liblzma compression library when it is linked into OpenSSH via systemd. The backdoor modifies RSA signature verification to enable unauthorized access. Multiple Linux distributions including Fedora 41, Debian testing, openSUSE Tumbleweed, and Kali Linux were affected before the backdoor was discovered. The discovery was made by Andres Freund, a Microsoft engineer, who noticed a 500ms latency increase in SSH connections.""",
    },
    {
        "id": "report_007",
        "content": """Server ALPHA in the manufacturing plant was compromised on January 15, 2026. Initial forensic analysis revealed traces of the DROPBEAR backdoor with command and control communications to 198.51.100.42. The malware was delivered through a spearphishing email containing a malicious macro document. Lateral movement was achieved using stolen credentials and Mimikatz. On January 16, the incident response team isolated Server ALPHA, rotated all domain admin credentials, and deployed EDR across the network. By January 20, Server ALPHA was rebuilt from clean images, patched, and returned to production. The firewall vulnerability CVE-2024-1111 that provided initial network access has been patched system-wide.""",
    },
    {
        "id": "report_008",
        "content": """Turla (also known as Snake, Venomous Bear, or Secret Blizzard) is a Russian state-sponsored threat actor attributed to the FSB. The group is known for sophisticated espionage campaigns targeting government and diplomatic entities. Turla has been active since at least 2004, making it one of the longest-running APT groups. The group's toolset includes the Carbon backdoor, the Kazuar RAT, the Gazer trojan, and the Snake rootkit. In 2024, Turla was observed compromising Pakistani APT infrastructure (Storm-0156) to conduct operations against Afghan and Indian targets, demonstrating its ability to hijack other threat actors' infrastructure. The group primarily targets government ministries, embassies, and military organizations.""",
    },
]

# ── CTI Queries ───────────────────────────────────────────────────────────────
# Real questions an analyst would ask

CTI_QUERIES = [
    # Tool/malware attribution
    {"question": "What tools does APT28 use?", "gold": "Cobalt Strike, DROPBEAR, SedUploader", "category": "tool-attribution"},
    {"question": "What malware does Lazarus Group deploy?", "gold": "Manuscrypt RAT, TraderTraitor", "category": "tool-attribution"},
    {"question": "What tools does MuddyWater use?", "gold": "PowGoop, Small Sieve, Dindoor backdoor, PowerShell", "category": "tool-attribution"},
    {"question": "What tools does Turla use?", "gold": "Carbon backdoor, Kazuar RAT, Gazer, Snake rootkit", "category": "tool-attribution"},
    {"question": "What techniques does Volt Typhoon use?", "gold": "living-off-the-land, PowerShell, WMI, netsh", "category": "tool-attribution"},

    # CVE linkage
    {"question": "What CVE did APT28 exploit?", "gold": "CVE-2024-1111", "category": "cve-linkage"},
    {"question": "What is CVE-2024-3094?", "gold": "supply chain backdoor in XZ Utils", "category": "cve-linkage"},
    {"question": "Link CVE-2026-3055 to a threat actor", "gold": "MuddyWater, Dindoor backdoor, Microsoft Exchange", "category": "cve-linkage"},
    {"question": "What CVE did Lazarus exploit in 2024?", "gold": "CVE-2024-21887, Ivanti Connect Secure", "category": "cve-linkage"},

    # Actor attribution
    {"question": "Who is attributed to MOIS?", "gold": "MuddyWater", "category": "attribution"},
    {"question": "Who targeted cryptocurrency exchanges?", "gold": "Lazarus Group", "category": "attribution"},
    {"question": "Who compromised US critical infrastructure?", "gold": "Volt Typhoon", "category": "attribution"},
    {"question": "Who uses SIM swapping and MFA fatigue?", "gold": "Scattered Spider", "category": "attribution"},
    {"question": "Who hijacked Pakistani APT infrastructure?", "gold": "Turla", "category": "attribution"},

    # Temporal/incident
    {"question": "When was Server ALPHA compromised?", "gold": "January 15, 2026", "category": "temporal"},
    {"question": "Is Server ALPHA currently secure?", "gold": "rebuilt, patched, returned to production", "category": "temporal"},
    {"question": "When was the XZ Utils backdoor discovered?", "gold": "March 2024", "category": "temporal"},

    # Multi-hop
    {"question": "What APT group uses DROPBEAR and targeted NATO?", "gold": "APT28", "category": "multi-hop"},
    {"question": "Which Iranian group shares infrastructure with OilRig?", "gold": "MuddyWater", "category": "multi-hop"},
    {"question": "Who discovered the XZ Utils backdoor?", "gold": "Andres Freund", "category": "multi-hop"},
]


def keyword_judge(predicted: str, gold: str) -> float:
    """Keyword overlap scoring (same as LOCOMO benchmark)."""
    pred_lower = str(predicted).lower()
    gold_lower = str(gold).lower()
    if gold_lower in pred_lower:
        return 1.0
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


def run_strategy(strategy: str, k: int = 10) -> Dict:
    """Run CTI benchmark with a given ingestion strategy."""
    tmpdir = tempfile.mkdtemp(prefix=f"cti_bench_{strategy}_")
    mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl", lance_path=f"{tmpdir}/vectordb")

    # Ingest
    start = time.perf_counter()
    note_count = 0
    for report in CTI_REPORTS:
        if strategy == "full_session":
            mm.remember(report["content"], source_type="threat_report", source_ref=report["id"], domain="cti")
            note_count += 1
        elif strategy == "chunked_800":
            results = mm.remember_chunked(report["content"], source_type="threat_report", source_ref=report["id"], domain="cti", chunk_size=800)
            note_count += len(results)
    ingest_time = time.perf_counter() - start

    # Evaluate
    by_category = {}
    all_scores = []
    all_latencies = []

    for qa in CTI_QUERIES:
        cat = qa["category"]
        if cat not in by_category:
            by_category[cat] = {"scores": [], "latencies": []}

        start_q = time.perf_counter()
        results = mm.recall(qa["question"], k=k, exclude_superseded=False)
        latency = time.perf_counter() - start_q

        context = "\n".join(n.content.raw for n in results)[:3000]
        score = keyword_judge(context, qa["gold"])

        by_category[cat]["scores"].append(score)
        by_category[cat]["latencies"].append(latency)
        all_scores.append(score)
        all_latencies.append(latency)

    return {
        "strategy": strategy,
        "notes": note_count,
        "ingest_time_s": round(ingest_time, 1),
        "accuracy": round(sum(1 for s in all_scores if s == 1.0) / len(all_scores) * 100, 1),
        "avg_score": round(statistics.mean(all_scores), 3),
        "p50_latency_ms": round(statistics.median(all_latencies) * 1000, 0),
        "p95_latency_ms": round(sorted(all_latencies)[int(len(all_latencies) * 0.95)] * 1000, 0),
        "by_category": {
            cat: {
                "accuracy": round(sum(1 for s in stats["scores"] if s == 1.0) / len(stats["scores"]) * 100, 1),
                "avg_score": round(statistics.mean(stats["scores"]), 3),
                "p50_latency_ms": round(statistics.median(stats["latencies"]) * 1000, 0),
            }
            for cat, stats in by_category.items()
        },
    }


if __name__ == "__main__":
    print("=" * 70)
    print("  CTI Retrieval Benchmark")
    print(f"  Date: {datetime.now().isoformat()}")
    print(f"  Reports: {len(CTI_REPORTS)}, Queries: {len(CTI_QUERIES)}")
    print("=" * 70)

    # Run both strategies
    print("\n[1/2] Strategy: full_session (current)")
    full = run_strategy("full_session")
    print(f"  Notes: {full['notes']}, Accuracy: {full['accuracy']}%, p50: {full['p50_latency_ms']}ms")

    print("\n[2/2] Strategy: chunked_800")
    chunked = run_strategy("chunked_800")
    print(f"  Notes: {chunked['notes']}, Accuracy: {chunked['accuracy']}%, p50: {chunked['p50_latency_ms']}ms")

    # Comparison
    print("\n" + "=" * 70)
    print(f"{'Category':<20} {'full_session':>15} {'chunked_800':>15} {'Delta':>10}")
    print("-" * 70)

    all_cats = sorted(set(list(full["by_category"].keys()) + list(chunked["by_category"].keys())))
    for cat in all_cats:
        f_acc = full["by_category"].get(cat, {}).get("accuracy", 0)
        c_acc = chunked["by_category"].get(cat, {}).get("accuracy", 0)
        delta = c_acc - f_acc
        sign = "+" if delta > 0 else ""
        print(f"{cat:<20} {f_acc:>13.1f}% {c_acc:>13.1f}% {sign}{delta:>8.1f}%")

    print("-" * 70)
    delta_overall = chunked["accuracy"] - full["accuracy"]
    sign = "+" if delta_overall > 0 else ""
    print(f"{'OVERALL':<20} {full['accuracy']:>13.1f}% {chunked['accuracy']:>13.1f}% {sign}{delta_overall:>8.1f}%")
    print(f"{'p50 latency':<20} {full['p50_latency_ms']:>12.0f}ms {chunked['p50_latency_ms']:>12.0f}ms")
    print(f"{'Notes stored':<20} {full['notes']:>14} {chunked['notes']:>14}")
    print("=" * 70)

    # Save
    output = {
        "meta": {"date": datetime.now().isoformat(), "reports": len(CTI_REPORTS), "queries": len(CTI_QUERIES)},
        "full_session": full,
        "chunked_800": chunked,
    }
    results_path = "benchmarks/cti_retrieval_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved: {results_path}")

    # Verdict
    print(f"\n  VERDICT: ", end="")
    if chunked["accuracy"] > full["accuracy"]:
        print(f"chunked_800 wins (+{delta_overall:.1f}pp accuracy). MERGE.")
    elif chunked["accuracy"] == full["accuracy"]:
        if chunked["p50_latency_ms"] < full["p50_latency_ms"]:
            print(f"Same accuracy, chunked is faster. MERGE.")
        else:
            print(f"Same accuracy, same latency. NO CHANGE NEEDED.")
    else:
        print(f"full_session wins. DO NOT MERGE chunking change.")
