"""Loaded only by the configured, installed workspace-mcp executable."""
import os
import sys
from pathlib import Path

if os.environ.get('HERMES_GOOGLE_ADAPTER') == '1':
    try:
        from adapter import install
        install(Path(os.environ['WORKSPACE_MCP_CREDENTIALS_DIR']).parent.parent)
    except Exception:
        print('Google Workspace adapter initialization failed; check persistent account state.', file=sys.stderr)
        # sitecustomize exceptions otherwise get ignored by the Python interpreter.
        os._exit(1)
