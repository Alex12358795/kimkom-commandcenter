# Probe targets

Prometheus discovers HTTP and HTTPS endpoints from `targets/http.yml` and
`targets/https.yml`. Keep targets reachable from the CommandCenter host or the
`odoo-proxy` network. Prefer container or LAN addresses for HTTP checks; only
add DNS names where certificate monitoring requires them.

Example target group:

```yaml
- targets:
    - "http://service-name:8080/health"
  labels:
    environment: "development"
    owner: "kimkom"
```

The current Odoo `/metrics` endpoints are not usable, so Odoo is monitored by
HTTP probes instead of a hardcoded scrape target.

No backup timestamp metric is currently exported. Do not enable a metric
absence alert until a stable `kimkom_backup_last_success_timestamp_seconds`
series and expected instance labels exist; otherwise the alert would fire
permanently and could not identify a missing backup source safely.
