# VictoriaMetrics monitoring

The same Python hook/worker serves Claude Code and Codex. Routine collection, retries, queries and HTML
rendering execute as code; no language-model requests, extra Jev requests or agent turns are scheduled.
Linux and macOS use the same Python 3.11+ standard-library implementation (SQLite, POSIX locks, detached
subprocesses). No systemd, launchd, Docker or external collector is needed. Optional runtime-client version
detection uses bounded Linux `/proc` ancestry once during `SessionStart`; unsupported platforms
or unavailable evidence report an unknown client version without disabling telemetry.
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

`SessionStart` and `UserPromptSubmit` hooks run `telemetry-kick`: it only starts the worker when none holds the
lock — no state write, no network call, empty output. So delivery resumes after a client restart and keeps going
while the user works, without waiting for the next subagent.

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

Metrics describe call outcomes, selected model/effort candidates, active/shadow application, Jev request errors,
Jev and hook latency histograms, and direct Jev choices. Jev timing includes its internal retry;
one logical routing request can involve two HTTP attempts. No task text, descriptions, cwd, session IDs,
request IDs, task hashes or credentials are exported. Host names, project basenames and OS login names (or configured
aliases), client kind and observed versions are exported as cohort labels. Model selection is not proof of final execution:
a configured role may override it, or launching the subagent may fail.
Hook latency measures input parsing and routing through the point before telemetry enqueue/output; it does
not include the telemetry write itself or host-side tool execution. Storage lock waiting is capped at 100 ms.

Counter window totals and histogram quantiles are monitoring estimates. They do not establish task quality,
actual token/currency savings. Reported Jev usage is accounted separately below; downstream savings
require separately authorized usage and outcome data. Never label selection share as monetary savings.

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
worker exits, polling resumes on the next session start, user prompt or subagent; this is not a permanently running account
monitor. The agent can use `stats --account ALIAS --terminal` to show the snapshot in the answer.


## Usage coverage and historical data

Paid Jev usage includes `smr_jev_input_tokens_total` and `smr_jev_output_tokens_total`, each with
`smr_jev_<input|output>_known_token_requests_total` and
`smr_jev_<input|output>_unknown_token_requests_total` coverage counters. Input coverage, output coverage
and price coverage are independent; one field cannot fill in another. Forced Claude plugin reload may
invalidate its conversation cache; that host conversation cost is outside observed Jev usage.

Version 0.5.0 does not look up parent models or efforts in transcripts or lifecycle checkpoints.
The main terminal, HTML and Grafana dashboards omit obsolete tier/risk/review/probability and local-lookup
panels. Existing journal entries and VM history are preserved, not deleted or retrospectively relabelled.
Historical lookup counters describe old local I/O, not current routing or provider token usage.

## Observed runtime versions (0.4.8+)

Routing records carry the executing copy's `plugin_version` and `host`; `agent_version` identifies the
executing Claude Code/Codex client when runtime evidence is available, otherwise `unknown`. Model labels
are separate. A different installed executable found on PATH is not runtime-version evidence. At
`SessionStart` on Linux, a synchronous probe follows bounded process ancestry, retains the actual native
executable and asks it for `--version` with a two-second limit. It reads executable links and parent
process metadata, not process command lines, environments or transcripts. Ordinary routing hooks only
read the exact session/client cache: they do not inspect `/proc` or run a version subprocess.

Private state under the router config directory's `client-versions` stores hashes, a version (or unknown)
and time in bounded 0600 records inside a 0700 directory. Positive and failed probe observations expire
after 24 hours; repeated startup with the same session/executable identity reuses the cached observation.
Missing, expired, unsafe or conflicting state yields unknown, without a runtime probe on the routing path.
An old session must first emit `SessionStart` with the upgraded handler to populate this cache.
`smr_calls_total` includes these labels. The gauge
`smr_hook_version_last_seen_timestamp_seconds{instance,host,user,agent,plugin_version,agent_version}`
contains the timestamp of the actual routing hook observation. Worker delivery/heartbeats retain that
value; they cannot make an idle old hook look newly observed.

Reports list versions and age per reporter, retaining historical versions and flagging multiple observed
plugin/client combinations. Latest means most recently observed, not highest release number. Version
reporting follows instance/user/client filters independently of project filters. Missing reporter metadata
is shown separately; older samples are not retrospectively labelled. No fresh samples can mean idle
sessions, delivery gaps or uninstrumented old code: these data cannot prove all hosts are upgraded.

## Selection and submitted launch labels (0.5.0+)

A successful direct Jev decision records `reason="choice"`. `recommended_model` and `recommended_effort`
are the selected candidate, also in shadow mode. They are not a tier mapping. A native catalog candidate without effort support has null effort,
represented as unavailable or `not_supported` where the evidence supports that label.

`smr_calls_total.model` and `effort` describe submitted launch parameters. Source labels such as
`specified`, `original`, and `updated_input` distinguish explicit launch provenance; unknown parameters
remain `unknown`. Claude effort supplied through a bundled agent definition has
`effort_source=agent_definition`; Codex reasoning effort is a specified tool argument. `applied` separates
active rewrites from shadow recommendations. Shadow, skipped or failed calls have no inferred parent model
or effort; missing submitted parameters remain unknown. Original explicit parameters may still be observed.

A submitted alias is not a guaranteed Claude model revision, and submitted parameters do not prove the
child executed or used those values. Native policy, environment overrides, a role definition or a launch
failure can affect execution. Do not label these metrics actual runtime model/effort or realized savings.

The silent `claude-session` handler remains as a compatibility command name and initializes client-version
metadata at `SessionStart`, which also requests background native catalog discovery. It no longer tracks
model switches, session models or transcript paths. Version detection is independent of routing and retains
the bounded metadata-only probe described above.

Old samples can contain `inherit`, session-derived model sources, tier labels or lookup counters.
Upgrading does not turn those into direct selections, repair missing fields or delete remote history.

Native candidate metadata is distinct from version observations and submitted parameters. Codex supplies
visible model descriptions and effort descriptions from its native catalog. Claude supplies model-purpose
and capability fields from isolated SDK initialization; official effort guidance explains the reported
levels. `model_catalog_value`, `model_catalog_resolved_id` and `model_catalog_source` in local records are
catalog provenance, not child runtime observations. In particular, describing `opus` using an `opus[1m]`
row does not prove a launched child used that revision or context size. Catalog refresh is ordinary client
metadata work, without a user/model turn, an LLM research job or a Jev classification request.

Purpose descriptions are reused without a time expiry. Native discovery is driven by binary/catalog
file changes in Codex, binary changes and session starts in Claude, or a missing allowlist entry.
A new model identity or missing description refreshes metadata and prices for the full available
inventory. Catalog provenance therefore describes the latest discovery, not continuous observation of
the provider's current model availability.

Candidate model prices are separate from the Jev request-cost metrics above. They are official standard
API references in USD per million tokens, joined by exact provider model ID and accompanied by source
and freshness. An unknown price does not mean free usage; a stale price remains a previous observation.
Neither proves subscription charges, child execution costs or savings. Cache-read, cache-write and
context-band rates are separate categories and must not be collapsed into one token rate.

Local records may include `visible_task_estimate` and the selected model's `task_input_cost_estimate`.
They describe filtered task/description text using the coarse `utf8_bytes_div4_heuristic`, with explicit
approximate status. The full native child prompt is unknown; standard and long-context uncached input
costs are alternatives. These fields do not count the Jev request itself and do not replace its reported
input/output usage or cost metrics.
