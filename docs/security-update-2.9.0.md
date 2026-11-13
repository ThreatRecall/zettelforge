# Security update 2.9.0

This update raises vulnerable dependency minimums, refreshes pinned CI actions,
and disables Maigret username discovery until its upstream dependency constraint
can be fixed. It does not change the database format or publish a package release.

## Upgrade

Python **3.11 or newer** is required. Python 3.10 cannot resolve the patched
Pillow, filelock and dnspython releases used by this update. CI covers Python
3.11, 3.12 and 3.13.

Create a fresh virtual environment and install the extras you need:

```bash
python3.11 -m venv .venv-2.9
.venv-2.9/bin/python -m pip install --upgrade pip
.venv-2.9/bin/python -m pip install -e '.[dev,web]'
```

An ordinary upgrade does not remove dependencies that are no longer required.
Use a fresh environment to remove legacy Maigret and its vulnerable dependency
closure. Preserve your existing data directory and configuration. The collector
also refuses to import or run Maigret if it remains installed elsewhere.

## Dependency changes

| Dependency | New minimum / supported range |
| --- | --- |
| Requests | 2.33.0 |
| PyArrow | 23.0.1 |
| Pydantic | 2.4.0 |
| filelock | 4.2.1 |
| Pillow | 13.0.0 |
| Jinja2 | 3.1.6 |
| FastAPI | 0.162.5 through the 0.162.x series |
| LangChain Core | 1.3.3 |
| LiteLLM (optional) | 1.109.1 |
| dnspython (OSINT) | 2.9.0 |
| pytest (development) | 9.0.3 |

The explicit Pillow/filelock floors constrain fastembed's transitive dependency
chain. Lower-bound updates prevent an existing environment or resolver from
retaining known vulnerable versions simply because the old broad requirements
still allowed them. These are supported minimums, not a complete dependency lock.

## Maigret restriction

[CVE-2026-126190 / GHSA-mmhr-3c5m-f64f](https://github.com/advisories/GHSA-mmhr-3c5m-f64f)
describes excessive CPU consumption when SoupSieve matches descendant selectors
against deeply nested untrusted HTML/XML. The fix is SoupSieve 4.0. Maigret 0.6.6
requires SoupSieve below 3.0, including on its upstream main development line at
the time of review, so a compatible dependency-only fix is unavailable.

The `maigret_collector` registry entry remains for compatibility and identifies
itself as disabled. Calls return no records and log `maigret_collector_disabled`
with the advisory ID; no backend import or network request occurs. DNS, WHOIS,
breach and other OSINT collectors remain available. Re-enabling Maigret requires
an upstream compatible dependency declaration, a clean full audit and restored
backend regression coverage. Installing it manually is not a workaround.

## Validation and scope

On November 12, 2026, pip-audit 2.10.1 reported no known vulnerabilities in a
fresh Python 3.12 development/web installation (99 third-party distributions),
the Python 3.11 development/web resolution (100 distributions), or the Python
3.11 web/LangChain/LiteLLM resolution (97 distributions). No advisory exemptions
were applied. Resolution audits do not establish hosted-provider behavior.

The complete local test suite passed on Python 3.11 and 3.12: **802 passed,
15 skipped on each**, with 72.37% merged coverage. Configuration tests ran in a
separate process because an existing fixture deletes inherited `AMEM_DATA_DIR`;
all tests still executed. Lint, formatting, workflow validation, wheel/sdist
builds and package checks passed. The Maigret regression failed before disabling
the backend and passed afterward.

CI now audits the full development/web install without a fallback that silently
drops extras, upgrades its pip/audit tools, and removes obsolete advisory
exemptions. GitHub Actions remain pinned to full commit SHAs, including the
previously tag-only stale action. Snyk is conditional on its configured token.

This is dependency and targeted collector validation, not a claim that every
optional integration or all application code is vulnerability-free. GitHub's
Dependabot alert API was not accessible to the connected integration; the
dependency findings came from the PyPI advisory service used by pip-audit.
