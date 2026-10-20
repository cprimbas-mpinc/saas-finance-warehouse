"""Entry point for MCP clients. Works from any working directory:

    python /path/to/saas-finance-warehouse/mcp_server.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from finance_semantic.server import main  # noqa: E402

if __name__ == "__main__":
    main()
