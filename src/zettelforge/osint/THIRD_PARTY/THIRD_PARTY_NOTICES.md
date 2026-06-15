# Third-party notices — ZettelForge OSINT layer

Licenses of third-party material adopted or relied on by the OSINT layer.
ZettelForge is MIT-licensed; nothing here changes that.

## Apache-2.0 (adopted, attributed)

- **reconurge/flowsint** `flowsint-types` v1.2.8 — observable models
  (CryptoWallet, Transaction, SocialAccount) re-expressed in ZettelForge
  ontology shape. Full text: `LICENSE-Apache-2.0.txt`. Attribution: `NOTICE`.
  Pin + evidence: `PROVENANCE.md`.

## Runtime dependencies of the OSINT collectors (declared in `pyproject.toml` `[osint]`)

All permissive; reviewed and approved in AGE-118. License texts are obtained
at install time from the respective distributions; summarized here:

| Package | License | Use |
|---|---|---|
| python-whois (richardpenman) | MIT | domain WHOIS collector |
| dnspython | ISC | DNS record collectors |
| ipwhois | BSD-2-Clause | IP -> ASN/netblock WHOIS |

Planned additions for the enricher follow-up (record their notices when added):

| Package | License | Use |
|---|---|---|
| maigret (soxoj) | MIT | username -> SocialAccount enumeration |
| sherlock-project | MIT | username presence checks |

## Excluded (NOT used — recorded so they are never reintroduced)

| Package | License | Reason |
|---|---|---|
| holehe (megadose) | GPL-3.0 | copyleft contamination; abandoned 2021 |
| ignorant (megadose) | GPL-3.0 | copyleft contamination; abandoned 2021 |
| hibpwned (plasticuproject) | LGPL-3.0 | replaced by native HIBP REST call |
| psycopg2-binary (via flowsint-core) | LGPL-3.0 | core not adopted |
