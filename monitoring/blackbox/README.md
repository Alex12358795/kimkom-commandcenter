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

The CommandCenter now exports `kimkom_backup_*` metrics (last run timestamp,
last success timestamp, duration, etc.) from the managed nodes' backup scripts.
These are consumed by the `kimkom-backups` Prometheus alert rules
(`KimKomBackupFailed`, `KimKomBackupStale`, `KimKomBackupMetricsMissing`,
`KimKomRestoreVerificationFailed`, `KimKomRestoreVerificationStale`) and by the
"Backup – Status" Grafana dashboard (uid `kimkom-backup`). Do not enable a
metric-absence alert beyond the existing `KimKomBackupMetricsMissing` rule.
