"""Explicit ECS Exec import. Never invoked at container startup."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from urllib.parse import quote
import uuid

from configure import configure
from state import fsync_dir, locked, private_dir, validate_bundle, verify_identity, write_json


def import_bundle(bundle, account, home=Path('/opt/data'), replace=False, verify=verify_identity):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    account = validate_bundle(bundle, account)
    credentials = Credentials.from_authorized_user_info(bundle['credentials'])
    if not credentials.valid:
        credentials.refresh(Request())
    scopes = verify(credentials, account)
    # Use the actual grant, including hierarchy, rather than claimed bundle scopes.
    bundle = {**bundle, 'credentials': {**json.loads(credentials.to_json()), 'scopes': scopes}}
    validate_bundle(bundle, account)
    root = private_dir(Path(home) / 'integrations' / 'google')
    with locked(root):
        current = root / 'current'
        if current.exists() and not replace:
            raise ValueError('Existing account; pass --replace explicitly')
        if current.is_symlink():
            old = current.resolve()
            if old.parent != root / 'accounts':
                raise ValueError('Invalid persistent account pointer')
        elif current.exists():
            raise ValueError('Invalid persistent account pointer')
        else:
            old = None
        # Reject conflicting/malformed config before changing persistent credentials.
        configure(home, account, dry_run=True)
        accounts = private_dir(root / 'accounts')
        generation = private_dir(accounts / uuid.uuid4().hex)
        creds_dir = private_dir(generation / 'credentials')
        try:
            write_json(generation / 'client.json', bundle['client'])
            write_json(generation / 'account.json', {'account': account})
            write_json(creds_dir / (quote(account, safe='@._-') + '.json'), bundle['credentials'])
            fsync_dir(generation)
            fsync_dir(accounts)
            pending = root / ('.current-' + uuid.uuid4().hex)
            pending.symlink_to(generation.relative_to(root))
            os.replace(pending, current)
            fsync_dir(root)
        except BaseException:
            if not current.exists() or current.resolve() != generation:
                shutil.rmtree(generation)
            raise
        (root / 'reauthorize-required').unlink(missing_ok=True)
        configure(home, account)
        if old:
            shutil.rmtree(old)
    return account


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secret-arn', default=os.environ.get('GOOGLE_BOOTSTRAP_SECRET_ARN'))
    parser.add_argument('--account', required=True)
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--region', default='eu-west-1')
    args = parser.parse_args()
    if not args.secret_arn:
        parser.error('--secret-arn or optional Pulumi googleBootstrapSecretArn is required')
    try:
        import boto3
        response = boto3.client('secretsmanager', region_name=args.region).get_secret_value(SecretId=args.secret_arn)
        bundle = json.loads(response['SecretString'])
        if os.geteuid() == 0:
            os.setgroups([])
            os.setgid(10000)
            os.setuid(10000)
        import_bundle(bundle, args.account, replace=args.replace)
        print('Google Workspace credentials imported. Restart the gateway to discover MCP tools.')
    except Exception as error:
        # SDK/auth exceptions may contain response bodies and tokens; suppress their messages.
        print(f'Credential import failed ({type(error).__name__}). Check account, grant, EFS permissions, '
              'and existing state; use --replace only for explicit reauthorization.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
