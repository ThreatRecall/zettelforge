"""
ZettelForge Integrations — Framework wrappers for popular AI/agent libraries.

Available integrations:
    - langchain: ZettelForgeRetriever (LangChain BaseRetriever)
    - crewai:    ZettelForgeRecallTool / RememberTool / SynthesizeTool
                 (CrewAI BaseTool subclasses, optional dep —
                 ``pip install zettelforge[crewai]``)

Import semantics:
    - Importing this package (``import zettelforge.integrations``) eagerly
      imports the langchain module and therefore requires ``langchain-core``
      to be installed (``pip install zettelforge[langchain]``).
    - The CrewAI module is intentionally NOT imported here so callers who
      have not installed crewai can still ``import zettelforge.integrations``
      to use the LangChain wrapper. Import the CrewAI tools explicitly:
      ``from zettelforge.integrations.crewai import ZettelForgeRecallTool``.
"""

from zettelforge.integrations.langchain_retriever import ZettelForgeRetriever

__all__ = ["ZettelForgeRetriever"]
