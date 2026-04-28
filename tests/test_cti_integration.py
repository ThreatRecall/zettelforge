#!/usr/bin/env python3
"""
Test CTI Platform Integration with ZettelForge.
Validates bi-directional sync between memory and CTI DB.
"""
import sys
# Package installed via pip - no sys.path manipulation needed

from zettelforge.cti_integration import get_cti_connector, CTIPlatformConnector


def test_cti_connection():
    print("=== CTI Platform Integration Test ===\n")
    
    connector = get_cti_connector()
    
    # Test 1: Get stats
    print("[1] CTI Platform Statistics")
    stats = connector.get_stats()
    print(f"    Actors: {stats['threat_actors']}")
    print(f"    CVEs: {stats['cves']}")
    print(f"    CVEs in KEV: {stats['cves_in_kev']}")
    print(f"    IOCs: {stats['iocs']}")
    print(f"    Sectors: {stats['sectors']}")
    print(f"    Attack Techniques: {stats['attack_techniques']}")
    
    # Test 2: Search threat actors
    print("\n[2] Search Threat Actors (APT28)")
    actors = connector.search_cti("APT28", entity_type="actor")
    print(f"    Found {len(actors)} actors")
    for a in actors[:3]:
        print(f"    - {a['name']} ({a['country']}) - {a['actor_type']}")
    
    # Test 3: Search CVEs
    print("\n[3] Search CVEs (CVE-2024)")
    cves = connector.search_cti("CVE-2024", entity_type="cve")
    print(f"    Found {len(cves)} CVEs")
    for c in cves[:5]:
        print(f"    - {c['cve_id']} CVSS={c['cvss_score']} KEV={c['is_in_kev']}")
    
    # Test 4: Get active actors
    print("\n[4] Active Threat Actors (top 5)")
    active = connector.get_all_active_actors()[:5]
    for a in active:
        print(f"    - {a['name']} ({a['country']}) [{a['risk_level']}]")
    
    # Test 5: Recent KEVs
    print("\n[5] Recent KEVs (last 30 days)")
    kevs = connector.get_recent_kevs(days=30)
    print(f"    Found {len(kevs)} recent KEVs")
    for k in kevs[:5]:
        print(f"    - {k['cve_id']} CVSS={k['cvss_score']}")
    
    # Test 6: Import to memory format
    print("\n[6] Import Threat Actor to Memory Format")
    if actors:
        actor_data = connector.import_threat_actor(actor_id=actors[0]['id'])
        if actor_data:
            print(f"    Title: {actor_data['content'][:80]}...")
            print(f"    Metadata: {actor_data['metadata']}")
    
    print("\n=== Test Complete ===")
    return True


if __name__ == '__main__':
    try:
        success = test_cti_connection()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)