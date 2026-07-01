# Getting ZettelForge onto "awesome" lists — assessment & submission kit

This directory holds ready-to-submit materials and an honest eligibility
assessment for the two lists requested:

- `awesome-selfhosted/awesome-selfhosted`
- `sindresorhus/awesome`

> **Two hard constraints up front.** (1) These are third-party repos; the
> entries must be opened and merged by their maintainers via your own PR — they
> cannot be pushed from this project. (2) **Both lists explicitly ban
> AI-generated / AI-submitted entries** and will ban the contributor account for
> violating it. So the PR must be opened and worded *by you, personally*. The
> files here are a correctness aid (right format, right vocabulary, verified
> against the live rules), not a copy-paste-from-a-bot shortcut — review and
> rewrite the prose in your own voice before submitting.

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

1. Fork `awesome-selfhosted/awesome-selfhosted-data`.
2. Copy `zettelforge.yml` (this directory) to `software/zettelforge.yml` in your
   fork. Do **not** add `stargazers_count`, `updated_at`, `current_release`,
   `commit_history`, or `archived` — the bot fills those on merge.
3. Optionally run their linter locally:
   `make install && make` (it validates fields, tags, platforms, licenses).
4. Open a PR. Tick the checklist boxes honestly (project age, license,
   self-hostable, etc.). Write the PR description in your own words.
5. If you want a `demo_url`, only add one that points at a live demo of the
   *self-hosted software itself* (not the hosted ThreatRecall SaaS, which
   reviewers may treat as promotion). Left out by default.

---

## 2. sindresorhus/awesome — **not eligible as a project; only via a new list**

**ZettelForge cannot be listed here directly.** `sindresorhus/awesome` is a
"list of awesome lists." Its PR template states it accepts **only curated
awesome lists**, never individual tools or projects. There is no entry shape
that puts a single piece of software on that list.

The only legitimate route to appear there is to **create and submit your own
awesome list** (e.g. `awesome-cti-memory`, `awesome-threat-intelligence-tooling`,
or `awesome-agentic-memory`) in which ZettelForge is one of many entries. That
list — not ZettelForge — becomes the `sindresorhus/awesome` entry. Requirements
for such a list:

- Repo named `awesome-<topic>`, **default branch `main`**.
- At least **30 days old** (from first real commit / open-sourcing).
- License must be **CC0 / Creative Commons** (a code license like MIT is
  rejected); `LICENSE` file in root, no license section in the README.
- Awesome badge on the right of the H1; `Contents` ToC; `contributing.md`.
- Genuinely curated ("the best, not everything") and **not AI-generated**.
- Curating a topic that prominently features your own project, with little else,
  reads as self-promotion and gets rejected — the list has to be broadly useful
  on its own merits.

This is a real, multi-week effort and a separate decision from the
awesome-selfhosted submission. It is **not** scaffolded here because doing it as
a thin vehicle for one project is exactly what that list rejects. If you want to
pursue it, build the topic list for its own sake first, let it mature 30+ days,
then submit.

---

## Summary

| List | Verdict | Action |
|---|---|---|
| awesome-selfhosted | Eligible (frame as a web service) | Submit `zettelforge.yml` as `software/zettelforge.yml` — by hand, in your own words |
| sindresorhus/awesome | Not eligible for a single project | Only reachable by creating a separate, mature, CC0-licensed `awesome-<topic>` list |
