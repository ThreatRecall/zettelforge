# Flowsint adoption provenance (AGE-119)

Records the supply-chain evidence required by the AGE-118 security review
(go/no-go: CONDITIONAL GO) before any Flowsint-derived material entered
ZettelForge. Keep this file auditable.

## Pinned upstream source

- Repo: `reconurge/flowsint` (https://github.com/reconurge/flowsint)
- License: Apache-2.0 (root `LICENSE`, reproduced here as `LICENSE-Apache-2.0.txt`)
- Pinned ref: tag **v1.2.8**, commit **`2a4878c8fc06c13c16d91ce760873037fa0b6b6d`**
- Commit date: **2026-04-11** — on/after the 2026-01-25 relicense cutoff (REQUIRED)

## Relicense evidence (AGPL-3.0 -> Apache-2.0)

Upstream `NOTICE` states all code contributed before 2026-01-25 was originally
AGPL-3.0-or-later and was relicensed to Apache-2.0 "with the explicit written
consent of all contributors." We vendor ONLY from the post-relicense pinned
commit above; we never copy from pre-2026-01-25 git history. Residual risk
(the "all contributors consented" claim is not independently verifiable here)
is accepted per AGE-118 for a 6.7k-star actively-maintained project with an
explicit NOTICE. Upstream NOTICE carried forward in this directory's `NOTICE`.

## What was adopted vs. rejected

ADOPTED (Apache-2.0, attributed):
- Observable models CryptoWallet, Transaction, SocialAccount, re-expressed in
  ZettelForge ontology shape in `zettelforge/osint/ontology.py`. ASN and CIDR
  were NOT adopted — they already exist as `ASNumber` / `Netblock`.

NOT adopted (would have been duplication or non-compliant):
- `flowsint-enrichers` framework + `flowsint-core`: every enricher and the
  registry import `flowsint_core.core.enricher_base`. ZettelForge already has
  an equivalent, decoupled framework (`osint/transform_registry.py` +
  `osint/executor.py`, RFC-016), so the framework was reused, not vendored.
  Importing `flowsint-core` was also forbidden by AGE-118 (it pulls
  psycopg2-binary LGPL-3.0 and a Docker control SDK).

## Exclusions enforced (AGE-118)

- **holehe (GPL-3.0)** and **ignorant (GPL-3.0)** — copyleft, would
  contaminate MIT ZettelForge. Excluded. The pre-existing
  `collectors/people/holehe_collector.py` stub (which lazily imported
  `holehe`) was neutralized to a permanent compliant no-op under this issue;
  no `ignorant` path existed.
- **hibpwned (LGPL-3.0)** — not used. ZettelForge's breach path is a native
  HIBP REST call (`collectors/breach/hibp_collector.py`), per the review's
  preferred option.
- **Docker tool wrappers** (`tools/dockertool.py`, naabu/subfinder/dnsx/
  asnmap/mapcidr/httpx) — privileged Docker-control surface. Not adopted.

## Telemetry / hardcoded-host grep (AGE-118 gate)

Grep over `flowsint-enrichers/src` and `flowsint-types/src` at the pinned SHA
for `flowsint.io | reconurge. | telemetry | analytics | posthog | sentry |
mixpanel | api.flowsint`: only hits were `__author__ = "dextmorgn
<contact@flowsint.io>"` package metadata and the word "analytics" inside a
web-tracker type description. No callbacks/telemetry/exfil. PASS.

## Remaining gates owned by the follow-up issue

- Run `pip-audit` / OSV against the final pinned dependency set
  (python-whois, dnspython, ipwhois, and any maigret/sherlock additions) and
  attach the report to the implementation PR; fail merge on unresolved
  high/critical. Tracked in the AGE-119 enricher follow-up child issue.
