# AGE-120 dependency audit (AGE-118 gate)

GOV-009 / AGE-118 requires a pip-audit (OSV) run against the final pinned
OSINT dependency set, with high/critical findings blocking merge. The CI
`pip-audit` job (`.github/workflows/ci.yml`) is the enforcing gate; it audits
a clean `pip install -e ".[dev]"` closure on every PR. This file records the
local pre-merge evidence for AGE-120.

## Tool

`pip-audit 2.10.0` (OSV + PyPI advisory DB).

## Result

Audited the resolved dependency closure of the `[osint]` extra, split because
maigret/sherlock are declared but not installed in the dev box used for this
run:

| Requirement set | Packages (resolved closure) | Result |
|---|---|---|
| core osint | dnspython>=2.4.0, python-whois>=0.9.0, ipwhois>=1.2.0, httpx>=0.25.0 | No known vulnerabilities found |
| new osint (AGE-120) | maigret>=0.4.0, sherlock-project>=0.14.0 | One medium-severity transitive finding: CVE-2023-36464 / GHSA-4vvm-4w3v-6mr8 in PyPDF2 3.0.1 |

`httpx` (already a core dependency) backs both the native HIBP v3 REST call
and the block-explorer call, so `email_to_breaches` and
`wallet_to_transactions` add no new packages.

## Accepted medium finding

Maigret 0.6.1 currently declares `PyPDF2>=3.0.1,<4.0.0`. OSV reports
`CVE-2023-36464` against PyPDF2 3.0.1 with CVSS 6.2 and GitHub Advisory
severity `medium`; PyPDF2 has no patched release under that package name.
Upstream recommends migrating to `pypdf>=3.9.0`.

AGE-120 does not parse attacker-supplied PDFs or invoke Maigret's report
generation path. The ZettelForge collector lazy-imports Maigret only for
username account discovery and fails closed when the dependency is absent or
errors. Per GOV-009, the blocking threshold is HIGH/CRITICAL, so CI carries an
explicit `--ignore-vuln=CVE-2023-36464` with this citation.

## Notes

- The two HTTP enrichers contact their endpoints directly; no breach- or
  chain-specific package is introduced (see `THIRD_PARTY_NOTICES.md`).
- maigret/sherlock are lazy-imported and fail-closed in
  `collectors/people/maigret_collector.py`, so their absence at runtime is
  non-fatal; the declaration exists so the CI gate audits their closure.
- License compliance (AGE-118): maigret and sherlock-project are MIT; the
  excluded GPL (holehe/ignorant) and LGPL (hibpwned/psycopg2) packages are
  not present and are recorded in `THIRD_PARTY_NOTICES.md` to prevent
  reintroduction.
