"""Governed finance semantic layer + MCP server over the SaaS finance warehouse."""

from .catalog import SemanticError, load_catalog
from .service import FinanceSemanticLayer

__all__ = ["FinanceSemanticLayer", "SemanticError", "load_catalog"]
__version__ = "0.3.0"
