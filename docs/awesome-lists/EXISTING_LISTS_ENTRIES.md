# Paste-ready entries for existing curated lists

`sindresorhus/awesome` lists *awesome lists*, never individual projects, and the
two topics ZettelForge fits (threat intelligence, AI/agent memory) **already
have established lists** — so creating a new one would be rejected as a
duplicate. The realistic route into that ecosystem is to be an **entry inside an
existing, already-curated list**. Below are entries formatted to each target
list's exact convention.

> Same caveats as the selfhosted submission: these are third-party repos, so you
> open the PRs yourself, and you should reword the prose in your own voice.
> Verify the target section/columns against the neighbours at submit time — list
> formats drift.

---

## A. `hslatman/awesome-threat-intelligence` — the flagship CTI list

Section: **Frameworks & Platforms**. Entries are HTML table rows (name cell +
description cell). Drop this row in, alphabetically, matching the surrounding
`<tr>`/`<td>` structure:

```html
<tr>
    <td>
        <a href="https://github.com/rolandpg/zettelforge" target="_blank">ZettelForge</a>
    </td>
    <td>
        ZettelForge is a threat-intelligence knowledge base that extracts CVEs,
        threat actors, IOCs and MITRE ATT&amp;CK techniques from analyst notes
        and reports, resolves actor aliases (APT28 = Fancy Bear), and builds a
        STIX 2.1 knowledge graph queryable through a web UI, REST API and an
        MCP server.
    </td>
</tr>
```

## B. `topoteretes/awesome-ai-memory` — the AI-memory list (maintained by the Cognee team)

Pipe-table format with columns
`| Name | Description | URL | Open / Close | GitHub URL | Category | Storage |`.
Add, alphabetically:

```
| ZettelForge | Threat-intelligence memory and knowledge graph: extracts CVEs, actors, IOCs and ATT&CK techniques from analyst notes, resolves actor aliases, builds a STIX 2.1 graph with blended vector + graph retrieval, served over web UI, REST and MCP | https://docs.threatrecall.ai/ | Managed, Open source | https://github.com/rolandpg/zettelforge | Memory Tool | Graph, Vector |
```

(ZettelForge is already named as a peer of Mem0/Graphiti/Cognee in its own
README comparison table, so it slots naturally next to those entries here.)

---

## Why this, and not a new list

| Candidate new list | Blocker |
|---|---|
| `awesome-threat-intelligence` | `hslatman/awesome-threat-intelligence` is the established, widely-referenced one — a second is a duplicate reject. |
| `awesome-ai-memory` / `awesome-agent-memory` | Saturated: `topoteretes/awesome-ai-memory` plus ~6 others (TeleAI-UAGI, cxxz, tfatykhov, TsinghuaC3I, DEEP-PolyU). Duplicate reject. |

Landing in list **A** or **B** puts ZettelForge inside the same curated-list
ecosystem that `sindresorhus/awesome` indexes — which is the achievable version
of "listed on sindresorhus/awesome" for a single tool.
