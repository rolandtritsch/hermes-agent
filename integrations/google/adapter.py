"""Narrow v2.0.1 launch patch: local atomic store and serialized refresh."""
import json
from urllib.parse import quote

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from state import ROOT, RECOVERY, locked, write_json


def install(root=ROOT):
    from auth import credential_store, google_auth
    from auth.scopes import has_required_scopes
    from googleapiclient.http import HttpRequest

    # The pinned server requests three retries for Gmail sends/drafts. A 5xx
    # can follow a successful write, so enforce one attempt for every write
    # request at the installed Google API client's execution boundary.
    if not getattr(HttpRequest.execute, '_hermes_no_write_replay', False):
        original_execute = HttpRequest.execute

        def execute(request, http=None, num_retries=0):
            if request.method.upper() not in ('GET', 'HEAD'):
                num_retries = 0
            return original_execute(request, http=http, num_retries=num_retries)

        execute._hermes_no_write_replay = True
        HttpRequest.execute = execute

    class Store(credential_store.LocalDirectoryCredentialStore):
        def __init__(self):
            super().__init__(str(root / 'current' / 'credentials'))

        def account(self):
            return json.loads((root / 'current' / 'account.json').read_text())['account']

        def list_users(self):
            return [self.account()]

        def path(self, email):
            if email.lower() != self.account():
                raise google_auth.GoogleAuthenticationError('Google account mismatch; use the configured primary address')
            return root / 'current' / 'credentials' / (quote(email.lower(), safe='@._-') + '.json')

        def load(self, email):
            data = json.loads(self.path(email).read_text())
            return ManagedCredentials.from_authorized_user_info(data)

        def get_credential(self, email):
            with locked(root):
                return self.load(email)

        def store_credential(self, email, credentials):
            # Refresh persists under its own lock. Reject stale upstream saves.
            with locked(root):
                current = self.load(email)
                return current.token == credentials.token and current.refresh_token == credentials.refresh_token

        def delete_credential(self, email):
            raise RuntimeError('Use explicit operator revocation; account state is persistent')

    class ManagedCredentials(Credentials):
        def refresh(self, request):
            with locked(root):
                if (root / 'reauthorize-required').exists():
                    raise RefreshError(RECOVERY)
                email = store.account()
                latest = store.load(email)
                # Another connector may have refreshed since we loaded this object.
                if not latest.valid or latest.token == self.token:
                    try:
                        Credentials.refresh(latest, request)
                    except RefreshError as error:
                        # Transient failures may recover; terminal grants require explicit import.
                        if not getattr(error, 'retryable', False):
                            write_json(root / 'reauthorize-required', {'reauthorize': True})
                        raise RefreshError(RECOVERY) from None
                    write_json(store.path(email), json.loads(latest.to_json()))
                self.__dict__.update(latest.__dict__)

    store = Store()
    credential_store.set_credential_store(store)

    def get_credentials(user_google_email, required_scopes, **kwargs):
        if (root / 'reauthorize-required').exists():
            raise google_auth.GoogleAuthenticationError(RECOVERY)
        email = user_google_email or store.account()
        try:
            credentials = store.get_credential(email)
        except (OSError, ValueError, KeyError):
            raise google_auth.GoogleAuthenticationError(RECOVERY) from None
        if not has_required_scopes(credentials.scopes, required_scopes):
            raise google_auth.GoogleAuthenticationError(RECOVERY)
        if not credentials.valid:
            try:
                credentials.refresh(Request())
            except RefreshError:
                raise google_auth.GoogleAuthenticationError(RECOVERY) from None
        return credentials

    # Called by upstream's legacy authentication path. Raising instead of returning
    # None prevents its interactive flow from starting on missing/revoked credentials.
    google_auth.get_credentials = get_credentials
    return store
