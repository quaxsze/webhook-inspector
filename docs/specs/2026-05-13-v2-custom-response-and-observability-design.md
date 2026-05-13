# V2 Design — Custom response + Copy-as-curl + Custom observability

**Date** : 2026-05-13
**Author** : Stanislas Plum
**Status** : Validated — ready for implementation plan
**Prior phases** : V1 (Phases A → C) live in production at https://app.odessa-inspect.org

## Context

V2 extends V1 with three independent capabilities :

1. **Custom response per endpoint** — let the user define what status code, body, headers, and latency the ingestor returns when a webhook hits the endpoint. Required to simulate real-world webhook receivers (Stripe acks, GitHub responses, etc.).
2. **Copy-as-curl button** — a one-click frontend action that generates a ready-to-paste `curl` command from any captured request. Removes friction when the user wants to replay the request elsewhere (Postman, a different service, a local debugger).
3. **Custom observability** — domain-specific OTEL metrics, a Cloud Monitoring dashboard, and 5 alerting policies. This is the highest-value DevOps learning block of V2 — it teaches how to design SLIs and wire production-grade monitoring beyond traces.

Single monolithic PR, ~14h part-time effort, ~25 tasks in the implementation plan.

## Success criteria

1. An endpoint can be created with a custom `status_code`, `body`, `headers`, `delay_ms` ; the ingestor honors them on every captured request.
2. Existing endpoints created in V1 continue to work without migration friction (defaults preserve V1 behavior).
3. The viewer exposes a working "📋 copy as curl" button on every captured request.
4. At least 7 custom OTEL metrics are exported to Cloud Monitoring.
5. A single Cloud Monitoring dashboard renders all metrics + a few GCP-native ones (Cloud Run, Cloud SQL).
6. 5 alerting policies are configured ; at least one fires successfully on a manual incident drill (kill a Cloud Run instance, generate 5xx).
7. No production regression : V1 smoke test continues to pass after V2 deploy.

## Structural decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Scope structure | One monolithic V2 plan | User-requested. Three blocks (product features × 2 + observability) are coherent narratively. |
| Custom response complexity | Static + headers + latency simulation, **no templating** | YAGNI — templating opens XSS / parser-bug surface area for marginal gain. |
| Replay feature scope | Copy-as-curl button only (zero backend) | Genuine "replay to target URL" is V3 (forward feature). Copy-as-curl is the 80/20 user value. |
| Custom metric exporter | `opentelemetry-exporter-gcp-monitoring` (sibling of the `gcp-trace` lib used in Phase C) | Uses ADC out of the box. Manual OTLP gRPC auth is painful. |
| Notification channel | Single email channel to maintainer | PagerDuty/Discord overkill for V2 ; will be revisited in V6 SRE phase. |
| Dashboard authoring | Terraform `google_monitoring_dashboard` with inline JSON | Versioned. Trade-off against readability — accepted. |
| Background gauge updater | Async task in app service lifespan, 60s tick | Active endpoints count is a gauge, requires periodic sampling. App service (min=1) is always-on, ideal host. |

## Out of scope (deferred)

| Item | Phase |
|------|-------|
| Response body templating (`{{request.path}}`) | Possibly never — XSS / parser risk vs YAGNI |
| Forward webhook to a target URL | V3 |
| Rate limiting / WAF | V4 |
| User auth + URL claiming + long retention | V5 |
| PagerDuty / Discord notification routing | V6 |
| Formal SLO / error budget framework | V6 |

---

## Block 1 — Custom response : data model + domain

### Migration

Single Alembic revision `0002_custom_response.py` adds 4 columns to `endpoints` :

```sql
ALTER TABLE endpoints
  ADD COLUMN response_status_code INT  NOT NULL DEFAULT 200,
  ADD COLUMN response_body        TEXT NOT NULL DEFAULT '{"ok":true}',
  ADD COLUMN response_headers     JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN response_delay_ms    INT  NOT NULL DEFAULT 0;
```

`ALTER TABLE ... ADD COLUMN ... DEFAULT <constant>` is `O(1)` on Postgres 11+ (no table rewrite) — safe online migration. Existing rows pick up the defaults logically without storage churn.

Rollback is trivial (`DROP COLUMN × 4`).

### Domain entity update

`src/webhook_inspector/domain/entities/endpoint.py` adds 4 fields with defaults :

```python
@dataclass(slots=True)
class Endpoint:
    id: UUID
    token: str
    created_at: datetime
    expires_at: datetime
    request_count: int = 0
    response_status_code: int = 200
    response_body: str = '{"ok":true}'
    response_headers: dict[str, str] = field(default_factory=dict)
    response_delay_ms: int = 0
```

`Endpoint.create()` accepts these as optional kwargs and runs validation :

| Validation | Bound |
|------------|-------|
| `response_status_code` | `100 <= x <= 599` |
| `response_delay_ms` | `0 <= x <= 30_000` |
| `len(response_body.encode("utf-8"))` | `<= 65_536` (64 KiB) |
| `response_headers` keys (case-insensitive) | not in `{"content-length", "transfer-encoding", "connection", "host", "date"}` |

Each failure raises a typed exception (`InvalidResponseStatusError`, `InvalidResponseDelayError`, `ResponseBodyTooLargeError`, `ForbiddenResponseHeaderError`) — caught at the web boundary and mapped to 400.

### Repository

`PostgresEndpointRepository.save` and `_to_entity` extended to map the 4 new columns.

---

## Block 2 — Custom response : API

### `POST /api/endpoints`

Request body becomes optional ; if absent, defaults apply (V1 behavior preserved).

```json
{
  "response": {
    "status_code": 200,
    "body": "{\"received\": true}",
    "headers": {"Content-Type": "application/json"},
    "delay_ms": 0
  }
}
```

Schema is a Pydantic model `CreateEndpointRequest` with a nested optional `response: CustomResponseSpec`.

Validation errors return `400 Bad Request` with a JSON body describing the violation :

```json
{ "detail": "response.delay_ms must be between 0 and 30000 (got 50000)" }
```

The `CreateEndpoint` use case is updated to accept these fields and pass them to `Endpoint.create`.

### Response of `POST /api/endpoints`

Echoed back so the user can confirm what was saved :

```json
{
  "url": "https://hook.odessa-inspect.org/h/abc...",
  "token": "abc...",
  "expires_at": "2026-05-20T...",
  "response": {
    "status_code": 200,
    "body": "{\"received\": true}",
    "headers": {"Content-Type": "application/json"},
    "delay_ms": 0
  }
}
```

---

## Block 3 — Ingestor : custom response application

`web/ingestor/routes.py`'s `capture()` handler is extended :

```python
async def capture(...):
    body = await request.body()
    # ... size check, capture use case ...

    endpoint = await endpoint_repo.find_by_token(token)  # already loaded in use case

    if endpoint.response_delay_ms > 0:
        await asyncio.sleep(endpoint.response_delay_ms / 1000)

    return Response(
        content=endpoint.response_body,
        status_code=endpoint.response_status_code,
        headers=endpoint.response_headers,
    )
```

In practice, the `CaptureRequest` use case already returns the `Endpoint` object — the route handler picks the response config off it. No extra DB query.

### Edge case — delay during high concurrency

If many slow-delay endpoints get hammered, Cloud Run instances stack up (default concurrency = 80 / instance). With max=20 instances and 30s delay, theoretical absorption capacity is 80 × 20 / 30 = ~53 requests/sec sustained for 30s delays. Acceptable for V2 ; would be revisited if abuse is observed.

### Edge case — `response_body` containing characters that break headers

`response_headers` is JSONB ; values are strings. FastAPI's `Response` does not auto-escape. We trust the user-supplied content (since they're the endpoint creator). Out of scope to defend against self-DoS.

---

## Block 4 — Custom response UI

The landing page `templates/landing.html` gets an **"Advanced options" disclosure** (HTML `<details>` element, collapsed by default) underneath the main "Create a webhook URL" button.

Expanded layout :

```
[ Create a webhook URL → ]

▶ Advanced options (default: 200 OK, {"ok":true})
   When expanded :
   - Status code      [ 200    ]
   - Response body    [ {"ok":true}                                ]
                      (textarea, 4 rows)
   - Headers (JSON)   [ {"Content-Type":"application/json"}        ]
                      (textarea, 2 rows)
   - Delay (ms)       [ 0      ]
```

The button submits a JSON body via HTMX :

```html
<button
  hx-post="/api/endpoints"
  hx-vals='js:buildCreatePayload()'
  hx-ext="json-enc"
  hx-swap="none"
  hx-on::after-request="...redirect to /{token} on success..."
>
```

A small JS helper `buildCreatePayload()` reads the advanced fields and returns `{ response: { status_code, body, headers, delay_ms } }` (skips empty values so defaults apply).

Errors (400 from API) are rendered inline below the button via `hx-target="#error"` + `hx-swap="innerHTML"`.

### Trade-off

`hx-ext="json-enc"` requires the json-encoding HTMX extension (added via CDN, +2KB). Worth it vs hand-rolling a JS fetch.

---

## Block 5 — Copy-as-curl

Pure frontend. Backend tweak : the `RequestList` Pydantic model (response of `GET /api/endpoints/{token}/requests`) gains 2 fields :

```python
class RequestItem(BaseModel):
    id: UUID
    method: str
    path: str
    headers: dict[str, str]     # NEW
    body_preview: str | None    # NEW
    body_size: int
    received_at: str
```

The SSE fragment template `request_fragment.html` adds a button :

```html
<li class="...">
  <button type="button"
          class="copy-curl-btn"
          aria-label="Copy as curl">
    📋
  </button>
  <span class="method">{{ req.method }}</span>
  ...
</li>
```

A single JS event listener (event delegation on `<ul id="requests">`) handles all current and future `.copy-curl-btn` clicks. Each `<li>` carries the data via these attributes :

- `data-method` — uppercase HTTP verb
- `data-url` — full ingestor URL (e.g. `https://hook.odessa-inspect.org/h/abc...`)
- `data-headers` — JSON-encoded `{header: value}` map (via `tojson` Jinja filter)
- `data-body` — JSON-encoded body preview string, or empty string when offloaded

The handler parses these, builds the `curl` command, and writes to `navigator.clipboard`.

For requests where `body_size > 8192` (body offloaded to GCS), the curl `-d` argument is replaced with `# body too large, not inline (size: <N> bytes)` — V2 doesn't fetch GCS blobs from frontend.

A small toast appears for 2s after copy ("Copied to clipboard").

Fallback for HTTP context / old browsers : `document.execCommand('copy')` via a temporary `<textarea>`. Acceptable degradation.

---

## Block 6 — Custom OTEL metrics

New module `src/webhook_inspector/observability/metrics.py` defines an `AppMetrics` class wrapping the OTEL `MeterProvider` :

```python
class AppMetrics:
    def __init__(self, meter: Meter) -> None:
        self.endpoints_created = meter.create_counter(
            "webhook_inspector.endpoints.created",
            description="Total endpoints created.",
        )
        self.requests_captured = meter.create_counter(
            "webhook_inspector.requests.captured",
            description="Total webhooks captured.",
        )
        self.body_size_bytes = meter.create_histogram(
            "webhook_inspector.requests.body_size_bytes",
            description="Distribution of captured body sizes.",
            unit="By",
        )
        self.capture_duration_seconds = meter.create_histogram(
            "webhook_inspector.requests.capture_duration_seconds",
            description="Latency from request arrival to capture commit.",
            unit="s",
        )
        self.active_endpoints = meter.create_observable_gauge(
            "webhook_inspector.endpoints.active",
            callbacks=[...],
        )
        self.active_sse = meter.create_up_down_counter(
            "webhook_inspector.sse.active_connections",
        )
        self.cleaner_deletions = meter.create_counter(
            "webhook_inspector.cleaner.deletions",
        )
```

### Domain port + adapter pattern

Following Clean Architecture, the use cases must NOT depend on OTEL directly. Introduce `MetricsCollector` ABC in `domain/ports/metrics_collector.py` :

```python
class MetricsCollector(ABC):
    @abstractmethod
    def endpoint_created(self) -> None: ...

    @abstractmethod
    def request_captured(
        self,
        *,
        method: str,
        body_offloaded: bool,
        body_size: int,
        duration_seconds: float,
    ) -> None: ...

    @abstractmethod
    def cleaner_deletion_run(self, deleted: int) -> None: ...
```

Adapter `infrastructure/observability/otel_metrics_collector.py` implements it on top of `AppMetrics`. Fake in tests : `tests/fakes/metrics_collector.py` (in-memory recording).

### Wire points

The `CreateEndpoint`, `CaptureRequest`, and `run_cleanup` use cases / functions **gain a constructor argument** (or signature parameter for `run_cleanup`) of type `MetricsCollector`. Existing tests using `FakeRepo` are updated to pass a `FakeMetricsCollector` too.

- `CreateEndpoint.execute` → `self.metrics.endpoint_created()`
- `CaptureRequest.execute` → wrap in `time.monotonic()` block, then `self.metrics.request_captured(method=..., body_offloaded=..., body_size=..., duration_seconds=...)`
- `run_cleanup` (in `jobs/cleaner.py`) → `metrics.cleaner_deletion_run(deleted)` before exit
- SSE handler `stream_for_token` → uses `AppMetrics.active_sse` directly (web concern, OK to skip the port abstraction)
- Active endpoints gauge : registered with a callback that runs `SELECT count(*) FROM endpoints WHERE expires_at > NOW()`. OTEL invokes this callback at each scrape (every 60s by default). The callback uses a short-lived session — and we wire it in the app service's lifespan, since min=1 keeps the service warm.

The dependency injection happens in `web/app/deps.py` and `web/ingestor/deps.py` : a singleton `MetricsCollector` is built once at startup and passed to use case factories.

### Cardinality discipline

Labels are tightly controlled :

| Metric | Labels |
|--------|--------|
| `endpoints.created` | (none) |
| `requests.captured` | `method` (uppercase HTTP verb), `body_offloaded` (bool) |
| `body_size_bytes` | `body_offloaded` |
| `capture_duration_seconds` | `success` (bool) |
| `active_endpoints` | (none) |
| `active_sse_connections` | (none) |
| `cleaner.deletions` | (none) |

No labels for `token`, `endpoint_id`, `source_ip`. Maximum cardinality combo : `requests.captured` has `8 methods × 2 booleans = 16 unique series`. Cloud Monitoring free tier handles up to 100s of series ; we are nowhere near saturation.

### Export pipeline

New Python dep : `opentelemetry-exporter-gcp-monitoring`.

`observability/metrics.py` exposes `configure_metrics(service_name, cloud_monitoring_enabled: bool)` mirroring the existing `configure_tracing` pattern. In prod (`CLOUD_METRICS_ENABLED=true`), uses `CloudMonitoringMetricsExporter`. In dev/test, `ConsoleMetricExporter`.

The lifespan handler in `web/app/main.py` and `web/ingestor/main.py` calls `configure_metrics(...)` after `configure_tracing(...)`.

For the cleaner / migrator (short-lived jobs), the metric exporter is **explicitly flushed** before exit (otherwise metrics may not propagate). `provider.force_flush(timeout_millis=5000)` in a `finally` block.

---

## Block 7 — Terraform : metrics export wiring

`infra/terraform/cloud_run_*.tf` files gain a new env var per service :

```hcl
env {
  name  = "CLOUD_METRICS_ENABLED"
  value = "true"
}
```

`infra/terraform/service_accounts.tf` adds an IAM binding loop :

```hcl
locals {
  monitoring_writer_sas = [
    google_service_account.ingestor.email,
    google_service_account.app.email,
    google_service_account.cleaner.email,
  ]
}

resource "google_project_iam_member" "metrics_writer" {
  for_each = toset(local.monitoring_writer_sas)
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${each.value}"
}
```

`infra/terraform/apis.tf` requires adding `monitoring.googleapis.com` to the `required_apis` list. **Phase B's bootstrap and Phase C's apis.tf did NOT include it** — verified by re-reading both. Without enabling this API, the GCP exporter calls would fail with a 403 PermissionDenied at runtime.

---

## Block 8 — Cloud Monitoring dashboard (Terraform)

`infra/terraform/monitoring_dashboard.tf` creates one dashboard via inline JSON :

```hcl
resource "google_monitoring_dashboard" "main" {
  dashboard_json = jsonencode({
    displayName = "webhook-inspector"
    mosaicLayout = {
      columns = 12
      tiles   = [ ... ]  # 12 tiles, 4 rows × 3 columns
    }
  })
}
```

### Tile inventory

| Row | Tile 1 | Tile 2 | Tile 3 |
|-----|--------|--------|--------|
| 1 | Requests captured / min (ingestor) | Endpoints created / min (app) | Active endpoints (gauge) |
| 2 | p50/p95/p99 ingest duration | Body size distribution (heatmap) | SSE active connections |
| 3 | Cloud Run 4xx + 5xx rates (ingestor) | Cloud SQL CPU % | Cloud SQL connections |
| 4 | Cleaner deletions / day | Cloud Run cold starts / hour | Logs error rate |

Custom metric tiles use the OTEL series ; GCP-native tiles use `run.googleapis.com/*` and `cloudsql.googleapis.com/*` MQL queries.

### Estimated JSON size

~400-600 lines of JSON inside `jsonencode(...)`. If unwieldy, candidate for extraction into a separate `dashboard.json` file loaded via `file("dashboard.json")`. Decision deferred to implementation time.

---

## Block 9 — Alerting policies (Terraform)

`infra/terraform/monitoring_alerts.tf` defines :

```hcl
resource "google_monitoring_notification_channel" "email_owner" {
  display_name = "Owner email"
  type         = "email"
  labels = { email_address = var.owner_email }
}

resource "google_monitoring_alert_policy" "high_p95_latency" { ... }
resource "google_monitoring_alert_policy" "high_5xx_rate" { ... }
resource "google_monitoring_alert_policy" "cloudsql_cpu" { ... }
resource "google_monitoring_alert_policy" "cloudsql_disk" { ... }
resource "google_monitoring_alert_policy" "cleaner_stale" { ... }
```

New variable `owner_email` in `variables.tf` (sourced from `terraform.tfvars`, gitignored).

### Alert configurations

| Alert | Metric | Condition | Window | Severity |
|-------|--------|-----------|--------|----------|
| High p95 ingest latency | `webhook_inspector.requests.capture_duration_seconds` | p95 > 1s | 5 min | Warning |
| High 5xx rate | `run.googleapis.com/request_count` filtered by `response_code_class="5xx"` | rate > 5% of total for 5 min | 5 min | Critical |
| Cloud SQL CPU | `cloudsql.googleapis.com/database/cpu/utilization` | > 0.80 | 10 min | Warning |
| Cloud SQL disk | `cloudsql.googleapis.com/database/disk/utilization` | > 0.90 | 5 min | Critical |
| Cleaner stale | `webhook_inspector.cleaner.deletions` count | no datapoint in last 26h | window 26h | Warning |

All policies share the same `notification_channels = [email_owner.id]`.

### Manual validation procedure

After `tofu apply`, force one alert intentionally :

```bash
# Trigger 5xx by hitting an endpoint at unhealthy time
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=NEVER  # temporary
# Send webhooks → all 5xx → alert fires in 5 min
gcloud sql instances patch webhook-inspector-pg-dev --activation-policy=ALWAYS  # restore
```

Document in `infra/terraform/README.md` post-merge.

---

## Block 10 — Documentation

| File | Update |
|------|--------|
| `README.md` | New "Custom response" section with API example. Roadmap : V2 → ✅ Live. |
| `infra/terraform/README.md` | "Monitoring & alerting" section : dashboard URL, list of alerts, manual drill procedure. |
| `CLAUDE.md` | Add metrics conventions : cardinality rules, port/adapter pattern, exporter choice (`gcp-monitoring`). |
| `docs/specs/` | This file (already committed). |

---

## Testing strategy

| Layer | Coverage |
|-------|----------|
| Unit tests (domain) | Endpoint validation : 5 failing-input tests + happy path |
| Unit tests (use cases) | CreateEndpoint with/without custom response, custom response echoed correctly |
| Unit tests (metrics) | `FakeMetricsCollector` records expected calls in 4 use-case scenarios. OTEL `InMemoryMetricReader` for adapter tests. |
| Integration tests (web) | POST /api/endpoints with various payloads + 4xx for invalid ; ingestor returns custom status/body/headers/delay ; list endpoint exposes new fields. |
| Integration tests (frontend backend) | `RequestItem` JSON shape includes headers + body_preview. |
| Manual | Copy-as-curl button (clipboard test), dashboard rendering, alert firing on drill. |

Estimated test delta : **+23 tests**. Total post-V2 : ~80 tests (vs 57 today).

---

## Migration risk & rollback

The migration is :
- **Forward-only safe** : Postgres 11+ `ADD COLUMN ... DEFAULT <constant>` is O(1).
- **Rollback-safe** : `DROP COLUMN × 4` works, but loses any non-default custom response values. Acceptable for a V2 rollback (early users would re-create their custom responses).
- **Backward-compatible behavior** : V1 endpoints in the DB get the defaults — no behavior change for existing users.

CI/CD migration order (already implemented in Phase C deploy workflow) :
1. New image built and pushed.
2. Migrator job runs `alembic upgrade head` → schema gets the 4 columns.
3. Cloud Run services updated with new image.

Between steps 2 and 3, old service code runs against the new schema (extra columns are ignored by V1 select queries). Safe.

---

## Risks identified

| Risk | Likelihood | Impact | Mitigation V2 |
|------|------------|--------|---------------|
| Ingestor latency explodes when a malicious user sets `delay_ms=30000` and hammers requests | Medium | Cloud Run instances saturate, legitimate requests queue | Hard 30s cap (validated server-side both at API and runtime). Cloud Run `max=20` provides headroom. Long-term : V4 rate limiting. |
| User stores phishing / illegal content in `response_body` and shares the URL | Medium | Reputation + legal | Not mitigated in V2. Manual takedown via cleaner / admin script if reported. V4 may add WAF body scanning. |
| OTEL custom metrics cardinality explodes | Low | Cloud Monitoring quota burn, dashboard slowdown | Strict label discipline (table in Block 6) — max 16 unique series across all metrics. Code review checks any new label addition. |
| GCP exporter for metrics relies on ADC ; auth misconfiguration leaks 403 at runtime | Low | Metrics silently stop, no application impact | Verified during initial deploy via dashboard data presence. Cleaner / migrator metrics use `force_flush` before exit (otherwise short-lived jobs lose datapoints). |
| `dashboard_json` HCL block grows past ~800 lines and becomes unreadable | Medium | Maintenance friction | Extract to `dashboard.json` + `file(...)` load if exceeded. Decision deferred to implementation. |
| Alerts trigger false positives during initial tuning | High | Notification fatigue | Each alert has a multi-window condition (5-10 min) to absorb transient spikes. Tune thresholds after first 30 days of real traffic. |

## Cost impact

| Component | Marginal cost |
|-----------|---------------|
| Custom OTEL metrics ingestion | Free up to 150 MiB/month. With 7 low-cardinality series, projected usage : ~5 MiB/month. **0€**. |
| Cloud Monitoring dashboard | Free. |
| Alert policies | Free up to 100 policies. We have 5. **0€**. |
| Email notification channel | Free. |
| Storage cost (4 new endpoint columns) | Negligible — average ~50 bytes per endpoint, total < 1 MB/year at current scale. |

Total V2 cost delta : **0€/month**.

---

## Roadmap impact post-V2

After V2 ships :

| Phase | Status | Focus |
|-------|--------|-------|
| V1 | ✅ Live | MVP + CI/CD + domain + Cloud Trace |
| **V2** | **🟢 In progress / shipping** | Custom response + copy-as-curl + custom OTEL metrics + dashboard + alerting |
| V3 | 🟡 Planned | Forward webhook to a target URL (Pub/Sub + worker + DLQ + retry) |
| V4 | 🟡 Planned | Rate limiting + Cloudflare WAF + Memorystore Redis |
| V5 | 🟡 Planned | Google OAuth auth + claimed URLs + long-term history |
| V6 | 🟡 Planned | Formal SLOs + error budgets + status page |

---

## ADR-light

### ADR-006 : No response body templating

**Decision** : `response_body` is a static string. No `{{request.path}}` / `{{header.X}}` substitution.
**Why** : Templating opens (a) XSS / injection risk if body is rendered HTML, (b) parser complexity, (c) marginal user value (Stripe et al. don't need it). YAGNI.
**Alternative rejected** : Jinja2 sandbox template rendering. Considered but rejected on YAGNI grounds.

### ADR-007 : MetricsCollector port + OTEL adapter

**Decision** : Use cases depend on `domain/ports/metrics_collector.py:MetricsCollector` ABC. OTEL implementation in `infrastructure/observability/`.
**Why** : Preserves Clean Architecture invariant (domain layer has zero external deps). Tests use `FakeMetricsCollector` — fast, no OTEL setup.
**Alternative rejected** : Directly use `opentelemetry.metrics.get_meter()` in use cases. Easier but couples domain to OTEL, breaks the existing pattern.

### ADR-008 : Single email notification channel

**Decision** : One `email` channel to maintainer ; no PagerDuty / Discord / SMS.
**Why** : Side-project, single maintainer. Multi-channel routing is V6 SRE work.
**Alternative rejected** : Discord webhook (free, instant). Tempting but out of V2 learning scope.

### ADR-009 : Custom response delay capped at 30s

**Decision** : `response_delay_ms <= 30_000`.
**Why** : Cloud Run instance concurrency = 80 ; a 30s delay × 80 = 40 mins of accumulated request-seconds per instance. With max=20 instances we absorb ~50 RPS sustained at 30s delays. Beyond 30s, attacker could DoS the service via slow-response endpoints.
**Alternative rejected** : Higher cap (e.g., 5 min). Unnecessary product feature, high abuse risk.

### ADR-010 : Dashboard as inline JSON in HCL

**Decision** : `google_monitoring_dashboard.dashboard_json = jsonencode({...})` in `monitoring_dashboard.tf`.
**Why** : Single source of truth, versioned, applied like any other resource. Trade-off : verbose ; ~500 lines of JSON. Acceptable for V2.
**Alternative rejected** : Extract to separate `.json` file + `file()` function. Considered but deferred — if HCL exceeds 800 lines, revisit.

---

## Definition of Done

- [ ] All 23 new tests pass locally and in CI
- [ ] `make lint`, `make type`, `make test` all green
- [ ] Migration applies cleanly (verified locally + on dev via CI/CD)
- [ ] Custom response works end-to-end on `https://app.odessa-inspect.org` : create endpoint with custom config, send webhook, observe custom response received
- [ ] Copy-as-curl button copies a valid curl command (manual test from browser, paste and run, command succeeds)
- [ ] Dashboard renders all 12 tiles with data after 10 min of traffic generation
- [ ] At least one alert successfully fires during a manual drill ; email received
- [ ] README + infra README updated
- [ ] V2 roadmap row in README flipped to "✅ Live"
