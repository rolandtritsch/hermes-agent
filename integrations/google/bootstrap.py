"""Browser consent on a workstation; stage validated credentials directly in AWS."""
import argparse
import json
import logging
from pathlib import Path
import sys
import uuid

from state import MANIFEST, validate_bundle, verify_identity


def authorize(client_path, account):
    from google_auth_oauthlib.flow import InstalledAppFlow
    client = json.loads(Path(client_path).read_text(encoding='utf-8'))
    installed = client.get('installed', {})
    if (installed.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth'
            or installed.get('token_uri') != 'https://oauth2.googleapis.com/token'):
        raise ValueError('Expected a Google Desktop OAuth client JSON')
    # Suppress OAuth callback URLs and token exchange debug logs even if the
    # workstation has configured verbose logging globally.
    for name in ('google_auth_oauthlib.flow', 'requests_oauthlib', 'oauthlib', 'urllib3'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    flow = InstalledAppFlow.from_client_config(client, scopes=MANIFEST['scopes'],
                                               autogenerate_code_verifier=True)
    # OAuthlib creates/verifies state. Loopback is local-only; PKCE protects code exchange.
    credentials = flow.run_local_server(host='localhost', bind_addr='127.0.0.1', port=0,
                                        access_type='offline', prompt='consent',
                                        login_hint=account, timeout_seconds=300,
                                        authorization_prompt_message='Open the browser to authorize Hermes.',
                                        success_message='Hermes authorization received. You can close this window.')
    scopes = verify_identity(credentials, account)
    data = json.loads(credentials.to_json())
    data['scopes'] = scopes
    bundle = {'schema': 1, 'account': account.lower(), 'client': client, 'credentials': data}
    validate_bundle(bundle, account)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--account', required=True)
    parser.add_argument('--region', default='eu-west-1')
    parser.add_argument('--profile', default='roland')
    args = parser.parse_args()
    try:
        import boto3
        bundle = authorize(args.client, args.account)
        secrets = boto3.Session(profile_name=args.profile, region_name=args.region).client('secretsmanager')
        result = secrets.create_secret(
            Name='hermes/google-bootstrap/' + uuid.uuid4().hex,
            Description='Temporary Google Workspace consent bundle; delete after explicit ECS import',
            SecretString=json.dumps(bundle),
            Tags=[{'Key': 'Purpose', 'Value': 'hermes-google-bootstrap'}],
        )
        print(result['ARN'])  # The ARN is the only transferable/non-secret output.
    except Exception:
        print('Bootstrap failed. Check browser consent, primary account, required scopes, and AWS access. '
              'No credentials were printed. If staging succeeded, inspect and remove the staging secret.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
