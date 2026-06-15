# AGE-120 dependency audit (AGE-118 gate)

GOV-009 / AGE-118 requires a pip-audit (OSV) run against the final pinned
OSINT dependency set, with high/critical findings blocking merge. The CI
`pip-audit` job (`.github/workflows/ci.yml`) is the enforcing gate; it audits
a clean `pip install -e ".[dev]"` closure on every PR. This file records the
local pre-merge evidence for AGE-120.

## Tool

`pip-audit 2.10.0` (OSV + PyPI advisory DB).

## Result: no known vulnerabilities

Audited the resolved dependency closure of the `[osint]` extra, split because
maigret/sherlock are declared but not installed in the dev box used for this
run:

| Requirement set | Packages (resolved closure) | Result |
|---|---|---|
| core osint | dnspython>=2.4.0, python-whois>=0.9.0, ipwhois>=1.2.0, httpx>=0.25.0 | No known vulnerabilities found |
| new osint (AGE-120) | maigret>=0.4.0, sherlock-project>=0.14.0 | No known vulnerabilities found |

`httpx` (already a core dependency) backs both the native HIBP v3 REST call
and the block-explorer call, so `email_to_breaches` and
`wallet_to_transactions` add no new packages.

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
