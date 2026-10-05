"""Exercise the independently installed server through its actual stdio protocol."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / 'integrations' / 'google'
RUNTIME = INTEGRATION / '.venv'
MANIFEST = json.loads((INTEGRATION / 'manifest.json').read_text())


def runtime_check(code, tmp_path):
    if not (RUNTIME / 'bin' / 'python').exists():
        pytest.fail('Run uv sync --directory integrations/google --frozen before testing')
    prefix = f"import sys; from pathlib import Path; sys.path.insert(0, {str(INTEGRATION)!r}); home = Path({str(tmp_path)!r})\n"
    result = subprocess.run([str(RUNTIME / 'bin' / 'python'), '-c', prefix + textwrap.dedent(code)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


BUNDLE = '''
import json
from state import MANIFEST
account = 'owner@example.org'
bundle = {'account': account, 'client': {'installed': {
    'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'fake'}},
    'credentials': {'token': 'fake-token', 'refresh_token': 'fake-refresh',
    'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'fake',
    'token_uri': 'https://oauth2.googleapis.com/token', 'scopes': MANIFEST['scopes'],
    'expiry': '2099-01-01T00:00:00Z'}}
'''


def test_import_and_replacement_preserve_configuration(tmp_path):
    runtime_check(BUNDLE + '''
from import_credentials import import_bundle
from state import validate_bundle
import yaml
home.joinpath('config.yaml').write_text(yaml.safe_dump({
    'mcp_servers': {'existing': {'command': '/existing'}},
    'skills': {'disabled': ['other'], 'auto_load': ['existing-skill']}}))
verify = lambda credentials, email: MANIFEST['scopes']
import_bundle(bundle, account, home, verify=verify)
config = yaml.safe_load(home.joinpath('config.yaml').read_text())
assert config['mcp_servers']['existing'] == {'command': '/existing'}
assert config['mcp_servers']['google_workspace']['tools']['include'] == MANIFEST['tools']
assert config['skills']['disabled'] == ['other', 'google-workspace']
assert config['skills']['auto_load'] == ['existing-skill', 'google-workspace-mcp']
root = home / 'integrations' / 'google'
first = (root / 'current').resolve()
try:
    import_bundle(bundle, account, home, verify=verify)
except ValueError as error:
    assert '--replace' in str(error)
else:
    raise AssertionError('overwrote existing credentials')
assert (root / 'current').resolve() == first
for path in first.rglob('*'):
    assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
import_bundle(bundle, account, home, replace=True, verify=verify)
assert not first.exists()
assert (root / 'current').resolve() != first
''', tmp_path)


def test_account_scope_and_offline_failures_import_nothing(tmp_path):
    runtime_check(BUNDLE + '''
from copy import deepcopy
from import_credentials import import_bundle
for field, value, expected in [('account', 'stranger@example.org', 'mismatch'),
                                ('scopes', [], 'scopes'),
                                ('refresh_token', None, 'refresh token')]:
    bad = deepcopy(bundle)
    (bad if field == 'account' else bad['credentials'])[field] = value
    try:
        import_bundle(bad, account, home, verify=lambda *_: (_ for _ in ()).throw(AssertionError('network')))
    except ValueError as error:
        assert expected in str(error)
    else:
        raise AssertionError('accepted invalid consent')
assert not (home / 'integrations' / 'google').exists()
''', tmp_path)


def test_concurrent_refresh_and_atomic_failure(tmp_path):
    runtime_check(BUNDLE + '''
import multiprocessing
import datetime
from import_credentials import import_bundle
from adapter import install
from state import atomic_write
from unittest.mock import patch
import_bundle(bundle, account, home, verify=lambda *_: MANIFEST['scopes'])
root = home / 'integrations' / 'google'
store = install(root)
credentials = store.get_credential(account)
credentials.expiry = datetime.datetime(2000, 1, 1)
# Seed expired state using the actual atomic persistence primitive.
from state import write_json
write_json(store.path(account), json.loads(credentials.to_json()))
context = multiprocessing.get_context('fork')
refreshes = context.Value('i', 0)
barrier = context.Barrier(2)
class Response:
    status = 200
    data = b'{"access_token":"refreshed-token","expires_in":3600,"token_type":"Bearer"}'
def request(**kwargs):
    with refreshes.get_lock():
        refreshes.value += 1
    return Response()
def worker():
    local = store.get_credential(account)
    barrier.wait(timeout=10)
    local.refresh(request)
    assert local.token == 'refreshed-token'
processes = [context.Process(target=worker) for _ in range(2)]
for process in processes: process.start()
for process in processes:
    process.join(15)
    assert process.exitcode == 0
assert refreshes.value == 1
path = store.path(account)
before = path.read_bytes()
with patch('state.os.replace', side_effect=OSError('fault injection')):
    try: atomic_write(path, 'invalid partial content')
    except OSError: pass
    else: raise AssertionError('fault not exercised')
assert path.read_bytes() == before
assert not list(path.parent.glob('.*'))
''', tmp_path)


def test_revocation_latches_and_account_is_enforced(tmp_path):
    runtime_check(BUNDLE + '''
from adapter import install
from import_credentials import import_bundle
from google.auth.exceptions import RefreshError
from auth import google_auth
import_bundle(bundle, account, home, verify=lambda *_: MANIFEST['scopes'])
root = home / 'integrations' / 'google'
store = install(root)
credentials = store.get_credential(account)
class Response:
    status = 400
    data = b'{"error":"invalid_grant","error_description":"secret-value-must-not-leak"}'
calls = []
def revoked(**kwargs):
    calls.append(1)
    return Response()
for _ in range(2):
    try: credentials.refresh(revoked)
    except RefreshError as error:
        assert '--replace' in str(error)
        assert 'secret-value' not in str(error)
    else: raise AssertionError('accepted revoked credentials')
assert len(calls) == 1
try: store.get_credential('stranger@example.org')
except google_auth.GoogleAuthenticationError as error: assert 'mismatch' in str(error)
else: raise AssertionError('accepted wrong account')
import_bundle(bundle, account, home, replace=True, verify=lambda *_: MANIFEST['scopes'])
assert not (root / 'reauthorize-required').exists()
''', tmp_path)


@pytest.mark.asyncio
async def test_installed_stdio_discovery_and_service_filtering(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    runtime_check(BUNDLE + '''
from import_credentials import import_bundle
from auth.scopes import get_scopes_for_tools
from importlib.metadata import version
assert version('workspace-mcp') == MANIFEST['version']
assert set(get_scopes_for_tools(MANIFEST['services'])) == set(MANIFEST['scopes'])
import_bundle(bundle, account, home, verify=lambda *_: MANIFEST['scopes'])
''', tmp_path)
    config = yaml.safe_load((tmp_path / 'config.yaml').read_text())['mcp_servers']['google_workspace']
    env = {**os.environ, **config['env'], 'PYTHONPATH': str(INTEGRATION)}
    env.pop('GOOGLE_SERVICE_ACCOUNT_KEY_FILE', None)
    env.pop('GOOGLE_SERVICE_ACCOUNT_KEY_JSON', None)
    # Import is tested above; use the same config and pinned installed executable.
    parameters = StdioServerParameters(command=str(RUNTIME / 'bin' / 'workspace-mcp'),
                                      args=config['args'], env=env)
    async with asyncio.timeout(45):
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.list_tools()
                names = {tool.name for tool in result.tools}
                assert names == set(MANIFEST['tools'])
                assert 'start_google_auth' not in names
                # Use Hermes' actual allowlist predicate, not a duplicate implementation.
                from tools.mcp_tool_registration import _make_tool_filter
                allow = _make_tool_filter('google_workspace', config)
                assert all(allow(name) for name in names)
                assert not allow('create_form')
                assert not allow('start_google_auth')
                wrong = await session.call_tool('list_calendars', {'user_google_email': 'stranger@example.org'})
                assert wrong.is_error
                assert 'mismatch' in str(wrong.content)


def test_hermes_registration_and_dispatch_use_the_pinned_server(tmp_path):
    runtime_check(BUNDLE + '''
from import_credentials import import_bundle
import_bundle(bundle, account, home, verify=lambda *_: MANIFEST['scopes'])
''', tmp_path)
    import sys
    sys.path.insert(0, str(INTEGRATION))
    from verify import register
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.mcp_tool_schema import mcp_prefixed_tool_name
    from model_tools import handle_function_call
    config_path = tmp_path / 'config.yaml'
    config = yaml.safe_load(config_path.read_text())
    server = config['mcp_servers']['google_workspace']
    server['command'] = str(RUNTIME / 'bin' / 'workspace-mcp')
    server['env']['PYTHONPATH'] = str(INTEGRATION)
    config_path.write_text(yaml.safe_dump(config))
    try:
        register(tmp_path)
        # Authentication fails before an external API request, through real Hermes dispatch.
        result = handle_function_call(mcp_prefixed_tool_name('google_workspace', 'list_calendars'),
                                      {'user_google_email': 'stranger@example.org'})
        assert 'mismatch' in str(result)
        assert 'Unknown tool' not in str(result)
    finally:
        shutdown_mcp_servers(names={'google_workspace'})


def test_google_api_write_errors_are_not_replayed(tmp_path):
    runtime_check('''
from adapter import install
from googleapiclient.http import HttpRequest
from googleapiclient.errors import HttpError
from httplib2 import Response
install(home / 'integrations' / 'google')
class Http:
    calls = 0
    def request(self, *args, **kwargs):
        self.calls += 1
        return Response({'status': '503', 'content-type': 'application/json'}), b'{"error":"uncertain"}'
http = Http()
request = HttpRequest(http, lambda response, content: content, 'https://example.invalid/write',
                      method='POST', body=b'{}')
try:
    request.execute(num_retries=3)
except HttpError:
    pass
else:
    raise AssertionError('uncertain write did not fail')
assert http.calls == 1
''', tmp_path)
