# VictoriaMetrics monitoring

The same Python hook/worker serves Claude Code and Codex. Routine collection, retries, queries and HTML
rendering execute as code; no language-model requests, extra Jev requests or agent turns are scheduled.
Linux and macOS use the same Python 3.11+ standard-library implementation (SQLite, POSIX locks, detached
subprocesses). No systemd, launchd, `/proc`, Docker or platform-specific collector is needed for telemetry.
State defaults to `~/.local/state/subagent-model-router/telemetry` on both systems, or `XDG_STATE_HOME` when set.
The user supplies VM endpoints. The plugin is independent of VPNs, network topology and hosting provider.

## Configure

Set `[telemetry]` in the existing private router config. The complete defaults are in
`../../../config.example.toml` (relative to this reference). For a VM single-node endpoint:

```toml
[telemetry]
backend = "victoriametrics"
write_url = "http://vm.example:8428/api/v1/import/prometheus"
query_url = "http://vm.example:8428"
instance = "workstation-router"
user = "" # OS login by default; optional shared alias
token_file = ""
flush_interval_seconds = 5
timeout_seconds = 3
max_queue_events = 1000
```

Use a different stable `instance` per installation writing counters. Claude and Codex on the same account
share one installation/state and are distinguished by `agent`. Every routing metric also has `project` and
`user`: project defaults to the nearest Git root directory name (cwd basename outside Git), user to the OS
login. No Git remote/config or full local path is sent. Directory-name collisions or differently named
checkouts can be aligned through `[telemetry.projects]` absolute-root-to-label mappings; the longest matching
path-component prefix wins. `telemetry.user` overrides the OS name with a stable alias. Avoid secrets in aliases.
These labels work the same for terminal and VS Code extensions; extensions use the account's plugin/config.
Do not use a session ID, task name or path
as the instance. Cluster write URL: `/insert/<tenant>/prometheus/api/v1/import/prometheus`; query base:
`/select/<tenant>/prometheus`. Copy actual authorized routes, do not infer the tenant.

HTTP and HTTPS endpoints are supported; HTTPS verifies certificates normally.
Optional `token_file` is a separate owner-only VM Bearer token file. Never put credentials in URLs or
show the token. Redirects are refused. No token is needed when the private endpoint uses only network ACLs.

`backend = "local"` preserves the original JSONL journal. `victoriametrics` stops appending that journal;
existing history is left untouched and is not uploaded automatically. `off` disables new statistics.
An invalid telemetry section disables collection and is reported by `check`/`stats`; routing still works.

## Delivery

The hook records aggregate counters/histograms in a private SQLite state store, then starts a detached
worker. It never waits for a VM HTTP request. A lock allows one sending worker per store; retries use the
same timestamped snapshot so an ambiguous response does not become a fresh counter increment.

Only bounded aggregate state and the pending delivery snapshot remain locally, not individual decision
records. A long outage coalesces updates: counts survive but event-time resolution does not. Extreme series
cardinality is capped; delivery diagnostics report drops. Hook storage contention/failure can lose telemetry
without blocking a subagent. This is operational monitoring, not an exactly-once billing ledger.

The worker is bounded to five minutes and restarted by later calls. It emits heartbeats while running;
after it exits, idle series may become stale. A final failed delivery remains pending until a later call
or an explicit `telemetry-worker` invocation. Disabling telemetry stops a worker on config reload.
No system service or client restart is needed for this delivery process.

## Statistics in the agent's answer

User-facing instructions are chat requests: “Show router statistics for the last week”, “Compare Codex and
Claude”, “Show project X for user Y”, or “Open the dashboard”. Do not ask users to execute commands, locate
plugin directories or open saved HTML files.

The agent resolves its installed plugin root and runs the following internal tools itself:

- `stats --days 7 --terminal` — ready-to-display Markdown dashboard: indicators, latency and Unicode charts.
- `stats --days 7 --project my-project --user kk573 --agent codex --terminal` — filtered VM dashboard.
- `stats --days 7 --terminal --browser` — same reply plus a short-lived URL for the agent's in-app browser.
- `stats --days 7 --terminal --open` — fallback when no in-app browser is available: ask the OS default
  browser to open the temporary page. An opener response does not prove a page was rendered.
- `telemetry-status` — local delivery health, no network call.
- `stats --source local --days 7 --terminal` — explicitly requested old journal statistics.

Always put the readable dashboard in the final answer; tool output and a link alone do not satisfy the
request. Charts/tables are rendered by Python, not regenerated by the LLM. Without a browser, the complete
terminal answer remains usable. Browser capability differs across terminal, VS Code and desktop clients;
only use an available documented browser tool, opening this new report without browsing unrelated tabs.
In remote/container environments a loopback URL belongs to that environment; do not send it to a browser
that cannot reach it or launch a remote browser as if it were on the user's desktop.

Browser HTML is served **from memory**, on 127.0.0.1 with a random port and unguessable path. No report file
is written. The worker exits after ten minutes, including if the agent exits. No credentials, raw task text,
remote scripts or CDN assets are included. Each report is independent; there is no fixed report filename.
If the user explicitly requests a downloadable/exported artifact, create a random private temporary filename
(mode0600) unless they supplied an explicit destination; `--html PATH` exists only for that export workflow.

VM queries are bounded to 1–90 days and limited response series/points. Errors never silently fall back to
local history. Missing data and gaps remain distinct from zero. Local terminal statistics use actual journal
observations; unavailable historical cohort fields or hook timings are not inferred.

For Grafana, the agent imports `../../../grafana/subagent-model-router.json` when authorized, with the user's
Prometheus-compatible VM datasource. It has instance/project/user/agent filters. Credentials belong in the
Grafana datasource. The browser report is a snapshot; Grafana queries current data.

Metrics describe call outcomes, selected models/tiers/effort, active/shadow application, Jev request errors,
Jev and hook latency histograms, and Jev decision probabilities. Jev timing includes its internal retry;
one logical routing request can involve two HTTP attempts. No task text, descriptions, cwd, session IDs,
request IDs, task hashes or credentials are exported. Project basenames and OS login names (or configured
aliases) are exported as cohort labels. Model selection is not proof of final execution:
a configured role may override it, or launching the subagent may fail.
Hook latency measures input parsing and routing through the point before telemetry enqueue/output; it does
not include the telemetry write itself or host-side tool execution. Storage lock waiting is capped at 100 ms.

Counter window totals and histogram quantiles are monitoring estimates. They do not establish task quality,
actual token/currency savings or the cost of the Jev request. Those require separately authorized usage and
outcome data. Never label selection share as monetary savings.

New counter series include a synthetic initial zero one flush interval before their first snapshot. This
allows first-batch counts to be seen, but timing within that interval is approximate. VM-side downsampling
or deduplication can merge samples and further affect small-window estimates. Coalesced/dropped delivery
health values are cumulative totals from the last received snapshot, not per-window increments.

## Money and OpenRouter balance

Jev response `usage.cost` is exported as `smr_jev_cost_usd_total` alongside
`smr_jev_known_cost_requests_total`, `smr_jev_unpriced_requests_total` and input/output token counters.
These costs describe observed router requests only and retain project/user/client cohorts. A missing cost,
failed request or timeout is unknown, not free. Retries with a lost response can incur unobserved cost;
period totals are monitoring estimates, not an invoice reconciliation. Old data has no retroactive prices.

For a user request to monitor their provider balance, set `openrouter_balance = true` and an explicit
`account = "my-openrouter"` under `[telemetry]`. Use the same alias only for the same account/key cohort;
use distinct aliases for different keys so per-key limits are not conflated. Reuse the configured OpenRouter
key file. Do not copy the OpenRouter key into the VM token file. The worker polls the fixed OpenRouter
`/api/v1/key` and `/api/v1/credits` endpoints, without calling Jev, every300 seconds per installation while
running. It persists last-attempt time across worker restarts. No external account fields or raw response
are retained, only allowlisted numerical gauges.

Key limit remaining and account credit balance are different. Account totals can include every application
using that account. Copies from several installations are selected by freshest successful snapshot, never summed. Inspect successful
probe flags and age before describing a snapshot as current; stale/forbidden balance is not zero. Unlimited
key limits are represented as unavailable amount plus explicit availability markers. After the five-minute
worker exits, polling resumes only on a later hook/worker start; this is not a permanently running account
monitor. The agent can use `stats --account ALIAS --terminal` to show the snapshot in the answer.


## Effective model labels (0.4.2+)

`smr_calls_total.model` holds the selected launch model, resolving inherited choices from the host event's
session model. `model_source=session|specified|unknown` explains the origin; `recommended_model` keeps Jev's
mapped recommendation separately, including in shadow mode. No model label contains `inherit` or `unchanged`.
If a host omits its session model or a custom role overrides it without observable evidence, it is `unknown`.
This remains a prelaunch observation, not proof of successful subagent execution. Claude aliases supplied
by the host remain aliases; the plugin does not invent a concrete model revision.

Old SQLite call counters without model_source are retired from new exports, including pending payloads;
other metrics/retries are retained. Existing VM history is not deleted or retrospectively relabelled.
Old `inherit` values can remain visible when the selected Grafana window includes older samples.


Since0.4.3 model-share groups by `(model, effort)`. `effort_source` distinguishes specified, session and
unknown values. Codex launch reasoning_effort is observed from effective tool arguments; inherited effort
uses host event data only when supplied. Claude2.1.280 supplies parent-turn `effort.level` but omits the model
from PreToolUse. For inherited general-purpose launches, the effort can be retained; for a changed child
model it is not evidence of child effort. Custom roles and absent evidence remain unknown. Config defaults
or ANTHROPIC_MODEL/CLAUDE_CODE_EFFORT_LEVEL are not substituted for current runtime observations. Old samples
are not retroactively repaired and retired call-series are no longer replayed by upgraded workers.
