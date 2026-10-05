"""Operator probes through Hermes' real MCP registration and dispatch path.

Run with /opt/hermes/.venv/bin/python, not the connector interpreter.
Tool results stay in a private file; stdout contains only a status.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys

from state import MANIFEST, locked, write_json

# Script execution sets sys.path[0] to this directory; Hermes lives above it.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def register(home):
    import yaml
    from tools.mcp_tool_discovery import register_mcp_servers
    from tools.mcp_tool_schema import mcp_prefixed_tool_name
    config = yaml.safe_load((home / 'config.yaml').read_text())['mcp_servers']['google_workspace']
    names = register_mcp_servers({'google_workspace': config})
    expected = {mcp_prefixed_tool_name('google_workspace', name) for name in MANIFEST['tools']}
    if set(names) != expected:
        raise RuntimeError(f'Google Workspace MCP discovery mismatch: missing={sorted(expected - set(names))}, '
                           f'extra={sorted(set(names) - expected)}')
    return config


def expire_token(home):
    root = home / 'integrations' / 'google'
    with locked(root):
        files = list((root / 'current' / 'credentials').glob('*.json'))
        if len(files) != 1:
            raise RuntimeError('Expected exactly one configured account')
        data = json.loads(files[0].read_text())
        data['expiry'] = '2000-01-01T00:00:00Z'
        write_json(files[0], data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', choices=MANIFEST['tools'])
    parser.add_argument('--arguments', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--expire-token', action='store_true')
    args = parser.parse_args()
    home = Path(os.environ.get('HERMES_HOME', '/opt/data'))
    if args.tool and (not args.arguments or not args.output):
        parser.error('--tool requires --arguments and --output paths')
    try:
        if args.expire_token:
            expire_token(home)
        config = register(home)
        if args.tool:
            from model_tools import handle_function_call
            from tools.mcp_tool_schema import mcp_prefixed_tool_name
            arguments = json.loads(args.arguments.read_text())
            arguments.setdefault('user_google_email', config['env']['USER_GOOGLE_EMAIL'])
            # Exactly one dispatch. Uncertain outcomes are left for operator inspection.
            result = handle_function_call(mcp_prefixed_tool_name('google_workspace', args.tool), arguments)
            write_json(args.output, {'tool': args.tool, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                     'result': result})
            parsed = json.loads(result) if isinstance(result, str) else result
            if isinstance(parsed, dict) and parsed.get('error'):
                raise RuntimeError('Tool failed; inspect the private result file before any retry')
        print('PASS: Google Workspace discovery' + (f' and {args.tool} dispatch; inspect private result' if args.tool else ''))
    except Exception as error:
        print(f'Google Workspace verification failed ({type(error).__name__}); '
              'inspect private results and connector status. Do not blindly retry a write.', file=sys.stderr)
        return 1
    finally:
        from tools.mcp_tool_lifecycle import shutdown_mcp_servers
        shutdown_mcp_servers(names={'google_workspace'})
    return 0


if __name__ == '__main__':
    sys.exit(main())
