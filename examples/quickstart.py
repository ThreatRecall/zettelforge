"""ZettelForge quickstart — runnable copy of the README's 30-second hello world.

Works on a fresh ``pip install zettelforge`` with NO Ollama, NO API keys, and
no other external services. Embeddings run in-process via fastembed
(downloaded on first call). Writes to ``~/.amem/`` by default; override with
``ZETTELFORGE_DATA_DIR`` if you don't want the demo to share storage with a
real workspace.

Run::

    pip install zettelforge
    python examples/quickstart.py

Expected output: three notes stored with auto-extracted entities, plus a
recall query that demonstrates threat-actor alias resolution
(Fancy Bear → APT28).
"""
from zettelforge import MemoryManager

mm = MemoryManager()

# Store threat intelligence — entities extracted automatically (regex; no LLM call)
note, status = mm.remember(
    "APT28 uses Cobalt Strike and XAgent for lateral movement. "
    "They exploit CVE-2024-3094 for initial access via T1021.",
    domain="security_ops",
)
print(f"Stored: {note.id} ({status})")
print(f"Entities: {note.semantic.entities}")

# Recall with alias resolution (APT28 = Fancy Bear). Blends vector + graph
# retrieval; no LLM required.
results = mm.recall("What tools does Fancy Bear use?")
for r in results:
    print(f"Found: {r.content.raw[:80]}...")
