# Adding a Status Provider

*For contributors working on the Mycelium source.*

A status provider lets board rows show the live state of something in another
tool. [Live pull request status](#board-reference) does this for GitHub.
Providers run only on the hub, where the token is, so the whole room shares one
cache.

A provider is a small class in `fastapi-backend/app/services/status/providers/`.
`providers/github.py` is a good one to copy. It sets a few options and
implements two methods:

```python
class JiraProvider:
    name = "jira"
    base_url = "https://your-org.atlassian.net"   # ctx.http only talks to this host
    auth = Basic("JIRA_EMAIL", "JIRA_TOKEN")  # which credentials, by name; the hub supplies the values
    max_batch = 50                  # most references to fetch in one call
    ttl = timedelta(minutes=1)      # how long an answer counts as current
    swr = timedelta(minutes=30)     # how long an older answer is still shown while it refreshes

    def claims(self, text: str) -> list[Ref]:
        """Find this provider's references in a row's text, e.g. PROJ-14."""

    async def fetch(self, refs: list[Ref], ctx: Context) -> list[Outcome]:
        """Look up a batch. Return one Ok or Err per reference, in any order."""
```

Only the provider knows what its references look like. Supporting a new kind,
such as Jira ticket keys, means adding a provider. Nobody lists what to watch.

`auth` says how the tool expects credentials and which names to look up:

| Auth | Sends | For |
|------|-------|-----|
| `Bearer("GITHUB_TOKEN")` | `Authorization: Bearer <token>` | GitHub, Asana, Sentry, Notion |
| `Basic("JIRA_EMAIL", "JIRA_TOKEN")` | HTTP basic auth | Jira Cloud |
| `Header("LINEAR_TOKEN")` | the raw token in `Authorization` | Linear |
| `Header("KEY", header="X-Api-Key")` | the raw token in a header you name | tools with their own header |

The provider never sees the token. `ctx.http` is already set up with the base
URL, the credentials, a timeout and retries. It refuses requests to any other
host, so a redirect or a hard-coded URL can't send credentials elsewhere. The
hub handles batching, de-duplication, caching and backing off when
rate-limited.

The hub also enforces two rules:

- **Batches only.** A hundred rows with `max_batch = 50` take two calls. If a
  tool can only look up one thing per request, set `max_batch = 1` and the hub
  paces the calls.
- **Each reference succeeds or fails on its own.** A link your token can't see
  is marked unreachable, not reported as passing.

Map the tool's states onto the board's six: `ok`, `pending`, `blocked`,
`failed`, `done` and `unknown`. Keep the tool's own wording as the label. The
answer lands on the row as `upstream`. It never goes in `status`, which is the
task's own stage. In the backend this is the `Liveness` type.
