"""Explicit deployment setup; preserves unrelated MCP and skill configuration."""
from pathlib import Path

import yaml
from state import MANIFEST, atomic_write, private_dir


def configure(home, account, runtime=Path('/opt/google-workspace'), install=Path('/opt/hermes'), dry_run=False):
    home = Path(home)
    root = home / 'integrations' / 'google'
    config_path = home / 'config.yaml'
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}
    config = config or {}
    servers = config.setdefault('mcp_servers', {})
    previous = servers.get('google_workspace')
    command = str(runtime / 'bin' / 'workspace-mcp')
    if previous and previous.get('command') != command:
        raise ValueError('An unrelated google_workspace MCP entry already exists')
    servers['google_workspace'] = {
        'command': command,
        'args': ['--transport', 'stdio', '--single-user', '--tool-tier', 'complete',
                 '--tools', *MANIFEST['services'], '--disabled-tools', 'start_google_auth'],
        'env': {
            'PYTHONPATH': str(install / 'integrations' / 'google'),
            'HERMES_GOOGLE_ADAPTER': '1',
            'WORKSPACE_MCP_CREDENTIALS_DIR': str(root / 'current' / 'credentials'),
            'GOOGLE_CLIENT_SECRET_PATH': str(root / 'current' / 'client.json'),
            'USER_GOOGLE_EMAIL': account,
            'WORKSPACE_MCP_CREDENTIAL_STORE_BACKEND': 'local_directory',
            'MCP_ENABLE_OAUTH21': 'false',
            'WORKSPACE_MCP_HTTP_PORT': '',
        },
        'trust': 'full',
        'sampling': {'enabled': False},
        'tools': {'include': MANIFEST['tools'], 'resources': False, 'prompts': False},
    }
    skills = config.setdefault('skills', {})
    for key, name in [('disabled', 'google-workspace'), ('auto_load', 'google-workspace-mcp')]:
        values = skills.setdefault(key, [])
        if isinstance(values, str):
            values = [values]
            skills[key] = values
        if name not in values:
            values.append(name)
    instructions = f'''---
name: google-workspace-mcp
description: Use the hosted Google Workspace account.
platforms: [linux]
---
# Google Workspace MCP

Use `google_workspace` MCP tools for Gmail, Calendar, Drive, Docs, Contacts,
Sheets, Tasks, and Slides. The primary account is `{account}`; always use this
address for `user_google_email`. Use the MCP tool schemas, not the disabled
`google-workspace` CLI skill. Other accounts require explicit operator setup.

Use explicit IANA timezones for events; default to `Europe/Dublin` and preserve
requested local times across daylight saving changes. Distinguish date-only
all-day events from timed events.

Read/search before editing an existing resource and use its returned ID.
When a send, share, create, update, or delete outcome is uncertain, inspect the
resulting resource before retrying. Never blindly repeat a write. If authorization
fails, report that the owner must reauthorize using workstation bootstrap and
ECS credential import with `--replace`; do not start browser login or retry
repeatedly. Read/write capability does not grant standing permission for
unsolicited sending, sharing, or other proactive actions.
'''
    if dry_run:
        return
    skill_dir = private_dir(home / 'skills' / 'google-workspace-mcp')
    atomic_write(skill_dir / 'SKILL.md', instructions)
    atomic_write(config_path, yaml.safe_dump(config, sort_keys=False))
