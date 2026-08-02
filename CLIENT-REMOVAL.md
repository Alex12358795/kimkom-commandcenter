# Client Removal Runbook

When a production client is decommissioned, its VM is repurposed for a different
client, or its Tailscale IP changes, you must manually prune its reporting
entries from the CommandCenter. None of the onboarding tooling (`init-client.sh`,
`install-monitoring.sh`) has a symmetric offboarding path — every step below is
performed by hand on this host.

Use this runbook when a client leaves, regardless of whether the underlying VM
is decommissioned or repurposed.

---

## When to use

| Trigger | Action |
|---|---|
| Client contract ends, stack torn down | Full removal: steps 1–8 |
| Client moved to a new VM, old VM repurposed | Removal on the old Tailscale IP (steps 1–6), then re-onboard via `init-client.sh` on the new VM |
| TEST VM repurposed for a different client pilot | Removal on the old client slug (steps 1–4), then `install-monitoring.sh --client-slug <new-slug>` on the same VM |

This is what happened on 30/07/2026: the TEST VM at `100.114.91.105` was
repurposed from `kimkom-prod` to `vranckeneers-prod` while the Prometheus scrape
targets and Cloudflare DNS still pointed at the old slug. The alerting stayed
silent on the old alerts (mute route) but the blackbox probes still returned 404
and `KimKomBackupMetricsMissing` fired because the node-exporter on the
vranckeneers stack has no `--collector.textfile.directory` mount for the
backup metrics.

---

## What needs removing

For client `<slug>` on Tailscale IP `<ts-ip>` serving `<domain>`:

1. Prometheus node-exporter target file (`nodes.yml`)
2. Prometheus postgres-exporter target file (`postgres.yml`)
3. Blackbox probe entries (`https.yml`) — both `pilot` and `production` labels
4. Orphan `https.yml.new` files in the blackbox targets directory
5. Cloudflare DNS records (out-of-band)
6. Tailscale node name (out-of-band)
7. Let's Encrypt cert (out-of-band, on the old VM)
8. GlitchTip project + DSN (optional)
9. Portainer endpoint (manual)
10. Documentation references in `AGENTS.md` and `SOP.md`

---

## Step 1 — Edit `nodes.yml`

Path: `/opt/kimkom-commandcenter/monitoring/prometheus/targets/nodes.yml`

Delete the block whose target IP matches `<ts-ip>:9100`:

```yaml
- targets:
    - "<ts-ip>:9100"
  labels:
    client: "<slug>"
    environment: "<production|pilot>"
    transport: "tailscale"
```

If the file becomes empty, leave a comment header in place so the next operator
knows where new entries are appended:

```yaml
# Placeholder for client scrape targets. Entries are appended by
# install-monitoring.sh (pilot) or init-client.sh phase 10 (production).
# Use CLIENT-REMOVAL.md to remove entries when a client is decommissioned or
# its VM is repurposed.
```

---

## Step 2 — Edit `postgres.yml`

Same edit for `<ts-ip>:9187` in
`/opt/kimkom-commandcenter/monitoring/prometheus/targets/postgres.yml`. Use the
same placeholder header if the file becomes empty.

---

## Step 3 — Edit `https.yml`

Path: `/opt/kimkom-commandcenter/monitoring/blackbox/targets/https.yml`

Delete both blackbox blocks for `<domain>`:

```yaml
# pilot block
- targets:
    - "https://<domain>/"
  labels:
    client: "<slug>"
    environment: "pilot"
    owner: "kimkom"
```

```yaml
# production block (HTTP-only probe; the HTTPS pilot block above covers 2xx)
- targets:
    - "http://<domain>"
  labels:
    client: "<slug>"
    environment: "production"
```

Do not touch the top dev block (supertcg/vranckeneers/kimkom-dev) unless you are
also removing those dev instances.

---

## Step 4 — Delete any orphan `*.new` files

```bash
ls /opt/kimkom-commandcenter/monitoring/blackbox/targets/
rm /opt/kimkom-commandcenter/monitoring/blackbox/targets/https.yml.new
```

`*.new` files are partial rewrites that did not replace the original. They are
not read by Prometheus and just create confusion.

---

## Step 5 — Reload Prometheus

```bash
cd /opt/kimkom-commandcenter
docker compose -f monitoring/docker-compose.yml --env-file .env restart prometheus
```

---

## Step 6 — Verify

Targets gone:

```bash
curl -s 'http://127.0.0.1:9090/api/v1/targets?state=any' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
                kp=[t for t in d['data']['activeTargets'] \
                    if t.get('labels',{}).get('client')=='<slug>']; \
                print(f'active <slug> targets: {len(kp)}')"
# Expect: active <slug> targets: 0
```

Alerts resolved (Prometheus stops emitting once the time series ages out;
Alertmanager's `resolve_timeout` is 5 minutes, so this may take up to ~5 min):

```bash
sleep 300
curl -s 'http://127.0.0.1:9093/api/v2/alerts?active=true&silenced=false&inhibited=false' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); \
                kp=[a for a in d if a.get('labels',{}).get('client')=='<slug>']; \
                print(f'active <slug> alerts: {len(kp)}')"
# Expect: active <slug> alerts: 0
```

If the alert count is non-zero after 5 minutes, query Prometheus directly for
the rule:

```bash
curl -sG 'http://127.0.0.1:9090/api/v1/query' \
  --data-urlencode 'query=up{job="client-nodes",client="<slug>"}'
# Should return no result — confirms the metric is gone.
```

---

## Step 7 — Cloudflare DNS (out-of-band, manual)

In the Cloudflare dashboard for the `kimkom.net` zone:

- Delete A records for `<domain>` and `*.<domain>`.
- If decommissioning entirely, also revoke the Let's Encrypt cert at
  `https://dash.cloudflare.com/?to=/:account/ssl-tls/edge-certificates`.
- If the domain will be reused for a different client on a different origin,
  repoint the A record to the new origin and update the Traefik host rule on
  the new VM.

There is no Cloudflare API integration in this repo — `AGENTS.md` §DNS documents
that records are managed out-of-band.

---

## Step 8 — Tailscale node name (out-of-band, manual)

In the Tailscale admin console (`https://login.tailscale.com/admin/machines`):

- **Repurpose:** rename the node from `<slug>` (or `<slug>-test`) to the new
  client's name, so MagicDNS matches what the VM actually serves.
- **Decommission:** disable the node's auth key and (optionally) delete the
  node from the tailnet.

---

## Step 9 — Let's Encrypt cert cleanup (out-of-band, on the old VM)

On the old client VM, as `alex` via the deploy key:

```bash
ssh -i /opt/kimkom-commandcenter/ssh/deploy_key alex@<ts-ip> \
  'sudo rm -rf /opt/kimkom-<slug>/volumes/traefik/letsencrypt && \
   sudo docker compose -f /opt/kimkom-<slug>/docker-compose.yaml \
        --env-file /opt/kimkom-<slug>/.env \
        restart traefik'
```

This avoids stale cert confusion if the VM is later repurposed for a different
domain.

---

## Step 10 — GlitchTip project (optional)

If the client had a GlitchTip project for error tracking:

- Find the project slug in `/opt/kimkom-commandcenter/glitchtip/dsns.json` (not
  committed; in the secrets tree).
- Delete via API:
  ```bash
  GLITCHTIP_TOKEN=$(cat /opt/kimkom-commandcenter/secrets/commandcenter/glitchtip-api-token)
  curl -fsS -X DELETE "http://100.67.52.95:8001/api/0/projects/<slug>/" \
    -H "Authorization: Bearer $GLITCHTIP_TOKEN"
  ```
- Remove the corresponding entry from `glitchtip/dsns.json` and the
  `GLITCHTIP_DSN` line from the old VM's `.env`.

---

## Step 11 — Portainer endpoint (manual)

If the old VM was added as a Portainer environment, remove it manually:
`http://100.67.52.95:9000 → Environments → <slug> → Remove`.

---

## Step 12 — Documentation updates

Update `/opt/kimkom-commandcenter/AGENTS.md` and
`/opt/kimkom-commandcenter/SOP.md`:

- Infrastructure table — VM role and client references
- §Directory Layout — client-specific paths that no longer apply
- §Module Workflow — references to `<slug>` client modules
- §Credentials Reference — secrets to archive or rotate

If the client's modules in `/opt/kimkom-modules/<slug>/` should be archived
before removal, push the final commit and create a `git tag archive/<slug>-<date>`
on the `kimkom-modules` repo.

---

## Notes

- **Reversibility.** All edits here are reversible. Re-running
  `install-monitoring.sh --client-slug <slug> --target-ts-ip <ts-ip>` re-adds
  the pilot scrape targets. Re-running `init-client.sh ... 10-monitoring-onboard`
  re-adds production targets and the blackbox entries.
- **Mute route.** Alertmanager silences `environment != "production"` — so
  pilot labels will not page. But `EndpointProbeFailed` (rule has no env
  filter) will, which is how a stale probe on a repurposed VM stays visible.
- **No automated tool exists yet.** A symmetric `uninstall-monitoring.sh`
  companion to `install-monitoring.sh` would cover steps 1–4 and the reload.
  If you remove a second client, build it.
- **Why the orphan `https.yml.new` exists.** Someone started editing
  `https.yml` and dropped it. These files are noise — delete them when you
  see one.