"""Private, durable state shared by bootstrap, import and the stdio adapter."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import tempfile

ROOT = Path('/opt/data/integrations/google')
MANIFEST = json.loads(Path(__file__).with_name('manifest.json').read_text())
RECOVERY = ('Google Workspace authorization is unavailable. Ask the owner to run the '
            'workstation bootstrap and ECS credential import with --replace. '
            'Do not retry writes or attempt browser login in ECS.')


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing a symlinked private directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


@contextlib.contextmanager
def locked(root):
    private_dir(root)
    fd = os.open(Path(root) / '.refresh.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Refusing to replace a symlinked file')
    fd, temporary = tempfile.mkstemp(prefix='.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, data):
    atomic_write(path, json.dumps(data, indent=2) + '\n')


def validate_bundle(bundle, expected):
    from auth.scopes import has_required_scopes
    account = bundle.get('account', '').strip().lower()
    if not expected or account != expected.strip().lower() or '@' not in account:
        raise ValueError('Google account mismatch')
    credentials = bundle['credentials']
    client = bundle['client'].get('installed', {})
    if not client.get('client_id') or not client.get('client_secret'):
        raise ValueError('A Desktop OAuth client is required')
    if credentials.get('client_id') != client['client_id'] or credentials.get('client_secret') != client['client_secret']:
        raise ValueError('OAuth client mismatch')
    if credentials.get('token_uri') != 'https://oauth2.googleapis.com/token':
        raise ValueError('Unexpected OAuth token endpoint')
    if not credentials.get('refresh_token'):
        raise ValueError('Offline refresh token is missing')
    if not has_required_scopes(credentials.get('scopes', []), MANIFEST['scopes']):
        raise ValueError('Required Google Workspace scopes are missing')
    if 'https://mail.google.com/' in credentials['scopes'] or any('admin.' in s for s in credentials['scopes']):
        raise ValueError('Administrator or permanent Gmail deletion scope is forbidden')
    return account


def verify_identity(credentials, expected):
    """Validate identity and actual grant online; never log token-bearing responses."""
    import requests
    from auth.scopes import has_required_scopes
    try:
        identity = requests.get('https://www.googleapis.com/oauth2/v2/userinfo',
                                headers={'Authorization': 'Bearer ' + credentials.token}, timeout=30)
        identity.raise_for_status()
        info = identity.json()
        # tokeninfo uses a POST body so the access token never enters a URL/log.
        grant = requests.post('https://oauth2.googleapis.com/tokeninfo',
                              data={'access_token': credentials.token}, timeout=30)
        grant.raise_for_status()
        grant_info = grant.json()
        scopes = grant_info.get('scope', '').split()
    except Exception:
        raise ValueError('Google identity/grant verification failed; reauthorize on the workstation') from None
    if info.get('email', '').lower() != expected.lower() or not info.get('verified_email'):
        raise ValueError('Google account mismatch')
    if grant_info.get('aud') != credentials.client_id:
        raise ValueError('OAuth grant client mismatch')
    if not has_required_scopes(scopes, MANIFEST['scopes']):
        raise ValueError('Required Google Workspace scopes are missing from actual grant')
    return scopes
