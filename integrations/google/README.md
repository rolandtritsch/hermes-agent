# Hosted Google Workspace MCP

This deployment adapter connects Hermes to `workspace-mcp==2.0.1` over stdio.
Its separate [lockfile][lock] fixes the server and every transitive dependency.
The production image installs `/opt/google-workspace/bin/workspace-mcp` during
build; connector startup performs no package downloads.

[manifest.json][manifest] captures the pinned release's complete tool tier for
Gmail, Calendar, Drive, Docs, Contacts, Sheets, Tasks, and Slides: 93 tools,
excluding `start_google_auth`. Hermes applies this explicit allowlist, grants
`trust: full`, and disables sampling. No HTTP MCP listener is enabled.

## Google project

The dedicated project is `tritsch-hermes-workspace` (number `750695471343`),
owned by the `tritsch.org` organization (`224996424227`). The eight APIs were
enabled on October 5, 2026. The primary account is `roland@tritsch.org`.

Use [Google Auth Platform][console] to configure **Internal** audience and a
**Desktop app** OAuth client. Download its JSON outside both repositories.
Google documents the [consent configuration][consent] and [Desktop client][client]
steps. Organization policy may require the administrator to approve this client.
This uses individual consent, with no service account or domain-wide delegation.

Scopes are derived from `auth.scopes.get_scopes_for_tools()` in the installed
release. They include Contacts write and broad Drive discovery/management,
Gmail send/compose/modify/settings, and all selected services. They exclude
administrator access and `https://mail.google.com/` permanent Gmail deletion.
The required scopes and tool names are checked against the actual server in tests.

## Workstation consent

From the Hermes checkout:

```sh
uv sync --directory integrations/google --frozen
integrations/google/.venv/bin/python integrations/google/bootstrap.py \
  --client /absolute/path/outside/repos/client.json \
  --account roland@tritsch.org --profile roland --region eu-west-1
```

The helper opens a browser and listens on a dynamically allocated loopback port.
OAuthlib verifies state and uses PKCE; consent requests offline access. The helper
verifies the account, actual grant, OAuth client, and refresh token before staging
anything. Tokens remain in memory and go directly to a temporary Secrets Manager
secret; no local bundle is written. Output contains only the staging ARN.

Do not paste client JSON, access tokens, or refresh tokens into chat, Pulumi
configuration, shell arguments, logs, or Git. Remove the downloaded client JSON
after successful import; retain any intentional backup in a restricted vault.

## ECS import and cleanup

Follow the infrastructure [deployment runbook][deployment] to grant the task role
access to the exact staging ARN and import using ECS Exec. Nothing imports during
container startup. The helper drops to UID/GID 10000, verifies the grant again,
refuses an existing account unless `--replace` is explicit, writes a complete
private generation, and atomically swaps its `current` pointer.

State lives below `/opt/data/integrations/google/`: directories are `0700`, files
are `0600`, and EFS encryption protects storage. These are JSON credentials,
without application-level encryption. Client configuration is outside the server's
credentials directory, so single-user discovery cannot mistake it for an account.

Explicit import preserves unrelated MCP entries and skill configuration, disables
the `google-workspace` CLI skill, and auto-loads account/timezone/write-outcome
routing instructions. Restart the gateway after import to discover tools in new
sessions. Existing conversations retain their cached toolsets until restarted.

The launch adapter replaces only the pinned server's local credential store and
legacy credential lookup. A stable EFS filesystem lock serializes refresh across
processes, and writes use fsync plus atomic replacement. Cached clients reload the
latest stored credentials before refreshing. Revoked grants latch
`reauthorize-required` and return recovery instructions instead of initiating
login or repeatedly contacting the token endpoint. Transient refresh errors do
not latch terminal state. The adapter also forces Google API write requests to
one attempt, overriding the pinned server's Gmail send/draft retry setting.
A successful explicit replacement clears the latch.

After import and verification, remove the ARN configuration and temporary IAM
permission, delete the staging secret, and remove the workstation client file.
If import fails, clean up the staging secret even when no account state was written.

## Verification

```sh
uv sync --frozen --extra dev --extra mcp
uv sync --directory integrations/google --frozen
scripts/run_tests.sh tests/integrations/google/test_workspace.py
```

Tests exercise real installed subprocess startup, MCP discovery and filtering,
configuration preservation, account/scope/offline-token rejection, replacement,
concurrent refresh, atomic-write fault handling, revoked-token recovery, real Hermes registry dispatch, and uncertain write errors
without replay.
They use isolated state and synthetic credentials, with no live API calls.

For operator probes through Hermes' actual MCP registration and dispatch path:

```sh
/opt/hermes/.venv/bin/python /opt/hermes/integrations/google/verify.py
# Expire the stored timestamp and then perform a read using --tool/--arguments/--output.
# --arguments is a private JSON file; --output receives the private tool result.
```

Live acceptance remains required before declaring this connection complete:

| Service | Disposable acceptance operations |
| --- | --- |
| Gmail | Read; create draft; send to owner; create/update label and apply it to test mail |
| Calendar | Create, read, update, delete event with `Europe/Dublin` timezone |
| Drive | Discover existing file; upload/download, rename, trash test file |
| Docs | Create, read, edit document; trash via Drive afterward |
| Sheets | Create, read, edit spreadsheet; trash via Drive afterward |
| Slides | Create, read, edit presentation; trash via Drive afterward |
| Contacts | Create, read, update, delete test contact |
| Tasks | Create, read, update, delete test task |

Use a unique `Hermes MCP acceptance <timestamp>` name and record returned resource
IDs before the next write. Test existing Drive discovery without changing the
existing file. Keep output to pass/fail and disposable resource IDs; do not print
private Gmail or existing file content. Verify resources when write outcomes are
uncertain rather than retrying blindly. Clean up only the recorded test resources.
The server has no draft-delete tool; remove the test draft in Gmail after checking
it. Send only to the owner, as authorized by the acceptance plan.

Expire the persisted access-token timestamp under the same filesystem lock, then
verify reads and atomic refresh. Replace the ECS task and repeat all service reads
without consent. Run a temporary Hermes scheduled job that edits the disposable
Doc with no interactive approval; verify the edit and delete the job. Revocation
handling is covered with an isolated failed token endpoint in tests; a live
revocation check requires revoking this dedicated grant, observing the latch,
then reauthorizing explicitly before the final reads.

## Recovery, backups, and rollback

Reauthorize by running workstation bootstrap again, staging a new bundle, and
importing with `--replace`. Remove temporary staging access afterward. Google
account revocation or deleting the OAuth client invalidates the grant; disabling
the MCP entry only stops connector use and does not revoke Google credentials.

Encrypted EFS backups include client configuration and refresh credentials.
Restrict backup/restore access accordingly. After compromise or intentional
revocation, do not restore an old grant as recovery: revoke the grant/client,
restore needed non-secret state, and explicitly reauthorize. Securely remove
obsolete credential generations and any restored `reauthorize-required` latch
only through successful replacement. Do not publish credential backups.

For rollback, set `mcp_servers.google_workspace.enabled: false`, restart Hermes,
and restore the previous immutable image digest using the deployment contract.
Keep persistent Google state for controlled reauthorization or a later release.

[lock]: uv.lock
[manifest]: manifest.json
[console]: https://console.cloud.google.com/auth/overview?project=tritsch-hermes-workspace
[consent]: https://developers.google.com/workspace/guides/configure-oauth-consent
[client]: https://developers.google.com/workspace/guides/create-credentials#desktop_app
[deployment]: https://github.com/rolandtritsch/pulumi-hermes/blob/trunk/docs/google-workspace.md
