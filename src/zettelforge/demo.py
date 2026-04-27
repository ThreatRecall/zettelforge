"""ZettelForge interactive demo — see CTI memory in action."""

import logging
import os
import tempfile
import time

# Sample CTI reports (real-world style, diverse entity types)
SAMPLE_REPORTS = [
    {
        "title": "APT28 Lateral Movement Campaign",
        "content": (
            "APT28 (also known as Fancy Bear) has been observed using Cobalt Strike "
            "for lateral movement in targeted campaigns against NATO-affiliated organizations. "
            "The group exploits CVE-2024-3094 (XZ Utils backdoor) for initial access, "
            "then deploys XAgent malware for persistence. MITRE ATT&CK technique T1021 "
            "(Remote Services) is the primary lateral movement method."
        ),
    },
    {
        "title": "Lazarus Group Cryptocurrency Theft",
        "content": (
            "Lazarus Group conducted a supply chain attack targeting cryptocurrency exchanges. "
            "The campaign used trojanized npm packages to deliver FALLCHILL malware. "
            "Indicators of compromise include the IP address 185.29.8.18 and the domain "
            "update-check.github-cloud[.]com. CVE-2023-42793 was exploited in the JetBrains "
            "TeamCity component. MITRE ATT&CK techniques T1195.002 (Supply Chain Compromise) "
            "and T1566.001 (Spearphishing Attachment) were observed."
        ),
    },
    {
        "title": "Volt Typhoon Infrastructure Targeting",
        "content": (
            "Volt Typhoon continues to target US critical infrastructure, focusing on "
            "communications, energy, and water sectors. The group uses living-off-the-land "
            "techniques, leveraging built-in Windows tools like netsh and PowerShell. "
            "No custom malware is deployed, making detection difficult. "
            "MITRE ATT&CK techniques T1059.001 (PowerShell) and T1018 (Remote System Discovery) "
            "are characteristic of their operations."
        ),
    },
    {
        "title": "CVE-2024-3094 Analysis",
        "content": (
            "CVE-2024-3094 is a critical backdoor discovered in XZ Utils versions 5.6.0 and 5.6.1. "
            "The backdoor was inserted through a sophisticated supply chain compromise of the "
            "open-source project. It targets SSH authentication on affected Linux distributions. "
            "The SHA-256 hash of the malicious payload is "
            "a]f5b6a8c7d9e2f1b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6. "
            "APT28 is suspected of involvement based on infrastructure overlap."
        ),
    },
    {
        "title": "Ransomware Trends Q1 2025",
        "content": (
            "Ransomware groups increasingly exploit Citrix NetScaler vulnerabilities "
            "(CVE-2023-4966, known as CitrixBleed) for initial access. BlackCat/ALPHV "
            "and LockBit affiliates have been the most active. The groups use Mimikatz "
            "for credential harvesting (T1003) and Metasploit for exploitation. "
            "Average ransom demands have increased 40% year-over-year."
        ),
    },
]


def run_demo():
    """Run the ZettelForge interactive CTI demo."""
    # Suppress noisy warnings from embedding/TypeDB fallbacks during demo
    logging.getLogger("zettelforge").setLevel(logging.ERROR)
    logging.getLogger("typedb").setLevel(logging.ERROR)

    print("=" * 60)
    print("  ZettelForge Demo — CTI Agentic Memory")
    print("=" * 60)
    print()

    # Use a temp directory so demo doesn't pollute user data
    tmpdir = tempfile.mkdtemp(prefix="zettelforge_demo_")
    os.environ["AMEM_DATA_DIR"] = tmpdir

    # Import after setting env
    from zettelforge import MemoryManager

    mm = MemoryManager(jsonl_path=f"{tmpdir}/notes.jsonl")

    # Phase 1: Ingest reports
    print("[1/4] Ingesting 5 CTI reports...")
    print()
    for i, report in enumerate(SAMPLE_REPORTS, 1):
        start = time.perf_counter()
        note, _status = mm.remember(report["content"], domain="security_ops")
        elapsed = (time.perf_counter() - start) * 1000

        # Show extracted entities
        entities = note.semantic.entities
        entity_str = ", ".join(entities[:5])
        if len(entities) > 5:
            entity_str += f" (+{len(entities) - 5} more)"

        print(f"  [{i}/5] {report['title']}")
        print(f"        Entities: {entity_str}")
        print(f"        Time: {elapsed:.0f}ms")
        print()

    # Phase 2: Entity recall by actor
    print("-" * 60)
    print("[2/4] Entity recall by threat actor...")
    print()
    print('  Query: mm.recall_actor("apt28")')
    results = mm.recall_actor("apt28", k=5)
    print(f"  Results: {len(results)} notes found")
    if results:
        print(f'  Top hit: "{results[0].content.raw[:80]}..."')
    else:
        # Fallback: show entity index has apt28 indexed
        stats = mm.indexer.stats()
        apt28_notes = mm.indexer.get_note_ids("intrusion_set", "apt28")
        print(f"  Entity index: APT28 indexed in {len(apt28_notes)} note(s)")
        if apt28_notes:
            note_obj = mm.store.get_note_by_id(apt28_notes[0])
            if note_obj:
                print(f'  Top hit: "{note_obj.content.raw[:80]}..."')
    print("  Note: APT28 = Fancy Bear — aliases stored in entity_aliases.json")
    print()

    # Phase 3: Semantic recall
    print("-" * 60)
    print("[3/4] Semantic recall across all memories...")
    print()
    print('  Query: mm.recall("supply chain attacks on open source")')
    results = mm.recall("supply chain attacks on open source", k=3)
    print(f"  Results: {len(results)} notes found")
    for i, note in enumerate(results[:3], 1):
        print(f"  [{i}] {note.content.raw[:70]}...")
    print()

    # Phase 4: Graph stats
    print("-" * 60)
    print("[4/4] Knowledge graph built automatically")
    print()
    stats = mm.indexer.stats()
    total_entities = sum(v["unique_entities"] for v in stats.values())
    total_mappings = sum(v["total_mappings"] for v in stats.values())
    print(f"  Total unique entities: {total_entities}")
    print(f"  Total entity-note mappings: {total_mappings}")
    print()

    # Show entity breakdown
    for etype, info in stats.items():
        if info["unique_entities"] > 0:
            print(f"    {etype}: {info['unique_entities']} entities")

    print()
    print("=" * 60)
    print("  Demo complete. Data stored in: " + tmpdir)
    print()
    print("  Next steps:")
    print("    from zettelforge import MemoryManager")
    print("    mm = MemoryManager()  # persists to ~/.amem/")
    print('    mm.remember("your threat intel here")')
    print()
    print("  Docs: https://docs.threatrecall.ai")
    print("  GitHub: https://github.com/rolandpg/zettelforge")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
