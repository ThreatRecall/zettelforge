# Getting ZettelForge onto "awesome" lists — assessment & submission kit

This directory holds reference examples and an eligibility assessment for
the two lists requested:

- `awesome-selfhosted/awesome-selfhosted`
- `sindresorhus/awesome`

> These are third-party repositories with independent contribution policies.
> Check each repository's current guidelines and PR template before preparing
> a submission. This directory does not authorize any external submission or
> establish that its examples are acceptable to a particular maintainer.

### Contribution policies by repository

| Repository | Current policy and guidance |
|---|---|
| [awesome-selfhosted-data](https://github.com/awesome-selfhosted/awesome-selfhosted-data/blob/master/CONTRIBUTING.md) | Requires a human-authored submission and prohibits machine/LLM-generated contributions, including an entry generated for a person to submit. The generated `zettelforge.yml` here is informational only and must not be submitted. A person posting or rewording generated text does not establish compliance. |
| [sindresorhus/awesome](https://github.com/sindresorhus/awesome/blob/main/pull_request_template.md) | Accepts curated lists, not individual tools. Its template rejects fully AI-generated PRs and requires the proposed list not to be AI-generated. Read the full template before considering a list submission. |
| [hslatman/awesome-threat-intelligence](https://github.com/hslatman/awesome-threat-intelligence/blob/main/CONTRIBUTING.md) | Its published guidelines require nonduplicate suggestions, one suggestion per PR, matching table formatting, and useful PR/commit titles. They do not currently state a blanket AI-submission ban; check the current policy before using an example. |
| [topoteretes/awesome-ai-memory](https://github.com/topoteretes/awesome-ai-memory#contributing) | Its contribution section asks for project metadata and a PR. It does not currently state a blanket AI-submission ban; check the current policy and requested columns before using an example. |

These policy summaries were checked on 2026-11-12. The linked upstream rules
are authoritative and can change independently of this directory.

---

## 1. awesome-selfhosted — **eligible, with one framing caveat**

awesome-selfhosted now lives in a data repo:
`github.com/awesome-selfhosted/awesome-selfhosted-data`. You add one YAML file
under `software/`; a bot renders the list and auto-fills stats.

### Criteria check (verified against the live CONTRIBUTING rules, 2026-06)

| Requirement | ZettelForge | Status |
|---|---|---|
| FOSS license (SPDX in `licenses.yml`) | MIT | ✅ |
| First released > 4 months ago, with tagged releases | v2.8.0, long release history | ✅ |
| Self-hostable **server** software (not desktop/mobile/CLI) | FastAPI web service + management SPA + auth, `Dockerfile` exposing :8000, `docker-compose.yml` | ✅ |
| No mandatory cloud / third-party dependency | Runs in-process (fastembed ONNX, llama-cpp, SQLite + LanceDB, Ollama on localhost); no API keys required | ✅ (so **no** `depends_3rdparty`) |
| Valid platform tag | `Python`, `Docker` | ✅ |
| Valid category tag (must already exist in `tags/`) | `Knowledge Management Tools` | ✅ (best existing fit) |
| Description rules: no "self-hosted"/"open-source"/"free", concise, ends with a period | see `zettelforge.yml` | ✅ |

**The one caveat — framing.** awesome-selfhosted explicitly excludes
"libraries, SDKs, or frameworks requiring application code." ZettelForge's
README leads with `pip install` + `from zettelforge import MemoryManager`, which
reads as a library. Reviewers are strict about this. The entry here is
therefore framed around the **self-hostable web service** (the FastAPI
management UI + REST API + Docker image), which is a genuine end-user
application and is what qualifies it. Keep that framing in the PR. If a reviewer
still pushes back on the library angle, point them at the Docker image and the
web UI screenshots/endpoints (`/`, `/api/recall`, `/api/graph/*`, config editor).

### How to submit

1. Read the current [contribution guidelines](https://github.com/awesome-selfhosted/awesome-selfhosted-data/blob/master/CONTRIBUTING.md)
   and [addition template](https://github.com/awesome-selfhosted/awesome-selfhosted-data/blob/master/.github/ISSUE_TEMPLATE/addition.md).
   A human must independently author any submission; do not copy or reword the
   generated `zettelforge.yml` here for submission.
2. If proceeding under those rules, fork the data repository and independently
   create `software/zettelforge.yml` from its upstream template. Do **not** add
   `stargazers_count`, `updated_at`, `current_release`, `commit_history`, or
   `archived` — the bot fills those on merge.
3. Optionally run their linter locally:
   `make install && make` (it validates fields, tags, platforms, licenses).
4. The human author may open a PR and complete the checklist truthfully
   (project age, license, self-hostable, etc.), including the authorship
   attestation. The PR description must also comply with the human-authorship
   requirement.
5. If you want a `demo_url`, only add one that points at a live demo of the
   *self-hosted software itself* (not the hosted ThreatRecall SaaS, which
   reviewers may treat as promotion). Left out by default.

---

## 2. sindresorhus/awesome — **not eligible as a project; reach it via an existing list**

**ZettelForge cannot be listed here directly.** `sindresorhus/awesome` is a
"list of awesome lists." Its PR template accepts **only curated awesome lists**,
never individual tools. There is no entry shape for a single piece of software.

**Creating a new list is a dead end too.** The two topics ZettelForge fits both
already have established lists, and `sindresorhus/awesome` rejects duplicate
topics:

- Threat intelligence → `hslatman/awesome-threat-intelligence` (the widely-used one).
- AI/agent memory → `topoteretes/awesome-ai-memory` plus ~6 others.

**The achievable path: become an entry inside one of those existing lists**,
which are themselves part of the awesome ecosystem `sindresorhus/awesome`
indexes. Draft entries illustrating their formats are in
[`EXISTING_LISTS_ENTRIES.md`](EXISTING_LISTS_ENTRIES.md). Before any external
submission, check the target repository's own current policy, verify the
entry, and follow its requested format and authorship requirements.

---

## Summary

| List | Verdict | Action |
|---|---|---|
| awesome-selfhosted | Assess as a web service under current rules | Human author starts from the upstream template; generated `zettelforge.yml` is informational only, not for submission |
| sindresorhus/awesome (directly) | Impossible for a single tool; new list = duplicate reject | — |
| via `hslatman/awesome-threat-intelligence` | Potential fit | Check current contribution policy and HTML-table format before preparing a submission |
| via `topoteretes/awesome-ai-memory` | Potential fit | Check current contribution policy and table columns before preparing a submission |

## External submissions are separate

This change only updates ZettelForge's own documentation. It does not open,
modify, or merge anything in the target repositories. A listing remains a
separate contribution subject to that repository's policy and maintainer
review; the authorship restrictions of one list do not automatically apply
to the others.
