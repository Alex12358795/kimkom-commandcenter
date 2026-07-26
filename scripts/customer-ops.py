#!/usr/bin/env python3
"""Secret-free customer inventory and managed Prometheus file-SD reconciler.

The JSON Schema is structural documentation only.  ``validate()`` is the sole
authoritative operational validator; schema acceptance must never be treated
as permission to mutate inventory, secrets, or targets.
"""
import argparse, contextlib, fcntl, ipaddress, json, os, re, tempfile, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "operations/customers.json"
LOCK = ROOT / "operations/customers.lock"
SECRET_ROOT = ROOT / "secrets/customer-ops"
NODE_DIR = ROOT / "monitoring/prometheus/targets/managed"
BLACKBOX_DIR = ROOT / "monitoring/blackbox/targets/managed"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.I)
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

def fail(message):
    raise SystemExit("customer-ops: " + message)

def valid_slug(slug):
    if not isinstance(slug, str) or not SLUG.fullmatch(slug): fail("invalid slug")
    return slug

def validate_endpoint(value, label, schemes=None):
    if not isinstance(value, str) or len(value) > 512 or any(x in value for x in ("@", "\\", "\n", "\r")):
        fail("invalid " + label)
    parsed = urllib.parse.urlparse(value if "://" in value else "//" + value)
    if schemes and parsed.scheme not in schemes: fail("invalid " + label + " scheme")
    if not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/"):
        fail("invalid " + label)
    try: port = parsed.port
    except ValueError: fail("invalid " + label + " port")
    if not schemes and (not port or not 1 <= port <= 65535): fail("invalid " + label + " port")
    if schemes and (parsed.query or parsed.fragment): fail("invalid " + label)
    return value

def validate_domain(value):
    if not isinstance(value, str) or not DOMAIN.fullmatch(value): fail("invalid production domain")
    return value.lower()

def normalized_name(value):
    """The reservation identity is case-folded, whitespace-collapsed display text."""
    return " ".join(value.split()).casefold()

def endpoint_host(value):
    parsed = urllib.parse.urlparse(value if "://" in value else "//" + value)
    return parsed.hostname.casefold() if parsed.hostname else None

def validate_production_targets(customer, record):
    # Host identity rule: management, node-exporter, and PostgreSQL exporter
    # targets must share one host; HTTP/HTTPS targets must use the customer
    # domain exactly (case-insensitively, with no path/query/fragment).
    domain = validate_domain(customer.get("domain"))
    for key, label, schemes in (("management_target", "management target", None), ("node_target", "node target", None), ("postgres_target", "PostgreSQL target", None), ("http_target", "HTTP target", {"http"}), ("https_target", "HTTPS target", {"https"})):
        validate_endpoint(record.get(key), label, schemes)
    for key, label in (("http_target", "HTTP target"), ("https_target", "HTTPS target")):
        if endpoint_host(record[key]) != domain:
            fail(label + " host must equal the production domain")
    management_host = endpoint_host(record["management_target"])
    if any(endpoint_host(record[key]) != management_host for key in ("node_target", "postgres_target")):
        fail("management, node, and PostgreSQL targets must use one host")

def validate(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("customers"), dict):
        fail("inventory must have schema_version=1 and an object customers")
    for slug, c in data["customers"].items():
        valid_slug(slug)
        if not isinstance(c, dict) or c.get("slug") != slug or not isinstance(c.get("name"), str) or not c["name"].strip():
            fail("invalid customer record for " + slug)
        if c.get("status") not in ("reserved", "active", "suspended"): fail("invalid customer status")
        g = c.get("glitchtip")
        project_slug = g.get("project_slug") if isinstance(g, dict) else None
        dsn_ref = g.get("dsn_ref") if isinstance(g, dict) else None
        if (not isinstance(project_slug, str) or not project_slug.strip()
                or dsn_ref != "secrets/customer-ops/" + slug + "/glitchtip-dsn"):
            fail("invalid GlitchTip reference for " + slug)
        ptn = c.get("portainer")
        if not isinstance(ptn, dict) or ptn.get("status") not in ("pending", "accepted"):
            fail("invalid Portainer status")
        if ptn.get("status") == "accepted" and not isinstance(ptn.get("endpoint_ref"), str): fail("accepted Portainer record needs endpoint_ref")
        if ptn.get("endpoint_ref") is not None and (not REF.fullmatch(ptn["endpoint_ref"]) or re.search(r"(?i)(token|password|secret|dsn|api[-_]?key)", ptn["endpoint_ref"])):
            fail("unsafe Portainer endpoint_ref")
        for env in ("development", "production"):
            record = c.get(env)
            if record is None: continue
            if not isinstance(record, dict) or not isinstance(record.get("active"), bool): fail("invalid " + env + " record")
            if env == "production" and record["active"]:
                validate_production_targets(c, record)
        # Extra non-secret fields are allowed, but credential-shaped values are not.
        raw = json.dumps(c, sort_keys=True)
        if re.search(r"(?i)://[^/\s]+@", raw) or re.search(r"(?i)(?:\"dsn\"|password|token|secret|api[_-]?key)\s*\"?\s*:", raw): fail("secret material in inventory")
    raw_inventory = json.dumps(data, sort_keys=True)
    if re.search(r"(?i)://[^/\s]+@", raw_inventory) or re.search(r"(?i)(?:\"dsn\"|password|token|secret|api[_-]?key)\s*\"?\s*:", raw_inventory):
        fail("secret material in inventory")
    return data

def load():
    if not INVENTORY.exists(): return {"schema_version": 1, "customers": {}}
    try: return validate(json.loads(INVENTORY.read_text()))
    except (OSError, ValueError) as e: fail("cannot read inventory: " + str(e))

def atomic_json(path, value, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent), text=True)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, indent=2, sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_DIRECTORY); os.fsync(dfd); os.close(dfd)
    finally:
        with contextlib.suppress(FileNotFoundError): os.unlink(name)

def atomic_text(path, text, mode):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(path.parent, 0o700)
    fd, name = tempfile.mkstemp(prefix=".secret.", dir=str(path.parent)); os.fchmod(fd, mode)
    try:
        with os.fdopen(fd, "w") as f: f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError): os.unlink(name)

@contextlib.contextmanager
def locked():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX); yield

def project(slug, name, args):
    # Callers validate slug before reaching this function.
    if args.dry_run: return slug, None
    token_path = ROOT / "secrets/commandcenter/glitchtip-api-token"
    if not token_path.exists(): fail("GlitchTip token is unavailable (use --dry-run)")
    token = token_path.read_text().strip(); base = args.glitchtip_url.rstrip("/")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    quoted = urllib.parse.quote(slug, safe=""); url = base + "/api/0/teams/kimkom/kimkom/projects/" + quoted
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r: existing = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code != 404: fail("GlitchTip lookup failed with HTTP " + str(e.code))
        req = urllib.request.Request(base + "/api/0/teams/kimkom/kimkom/projects/", json.dumps({"name": name, "slug": slug}).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r: existing = json.loads(r.read())
        except urllib.error.HTTPError as post:
            if post.code != 409: fail("GlitchTip create failed with HTTP " + str(post.code))
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r: existing = json.loads(r.read())
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/api/0/projects/kimkom/" + quoted + "/keys/", headers=headers), timeout=10) as r: keys = json.loads(r.read())
        dsn = keys[0].get("dsn") if isinstance(keys, list) else keys.get("dsn")
        if isinstance(dsn, dict): dsn = dsn.get("public") or dsn.get("dsn")
    except (KeyError, IndexError, TypeError, urllib.error.URLError): fail("GlitchTip response did not contain a DSN")
    if not isinstance(dsn, str) or not dsn: fail("GlitchTip response did not contain a DSN")
    secret = SECRET_ROOT / slug / "glitchtip-dsn"; atomic_text(secret, dsn + "\n", 0o600)
    return str(existing.get("slug", slug)), str(secret.relative_to(ROOT))

def targets(data):
    out = {"node": [], "postgres": [], "http": [], "https": []}
    for c in data["customers"].values():
        p = c.get("production")
        if not isinstance(p, dict) or not p.get("active"): continue
        common = {"client": c["slug"], "environment": "production", "managed_by": "kimkom", "domain": c["domain"]}
        for kind, key in (("node", "node_target"), ("postgres", "postgres_target"), ("http", "http_target"), ("https", "https_target")):
            out[kind].append({"targets": [p[key]], "labels": common})
    return out

def reconcile(data):
    out = targets(data)
    validate_rendered_targets(out)
    for kind, value in out.items():
        directory = NODE_DIR if kind in ("node", "postgres") else BLACKBOX_DIR
        atomic_json(directory / (kind + ".json"), value)

def validate_rendered_targets(out):
    if any(not isinstance(value, list) or any(set(x) != {"targets", "labels"} for x in value) for value in out.values()):
        fail("invalid generated target shape")

def main():
    ap = argparse.ArgumentParser(description=__doc__, epilog="customers.schema.json is structural-only; validate() is authoritative for operations."); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--glitchtip-url", default="http://100.67.52.95:8001")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("reserve"); r.add_argument("slug"); r.add_argument("--name"); r.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    for name in ("activate-production", "activate-development"):
        p = sub.add_parser(name); p.add_argument("slug"); p.add_argument("--name", required=name == "activate-production"); p.add_argument("--domain"); p.add_argument("--management-target"); p.add_argument("--node-target"); p.add_argument("--postgres-target"); p.add_argument("--http-target"); p.add_argument("--https-target")
    p = sub.add_parser("reconcile"); p.add_argument("slug", nargs="?")
    p = sub.add_parser("accept-portainer"); p.add_argument("slug"); p.add_argument("--endpoint-ref", required=True)
    sub.add_parser("validate", help="authoritative operational validation (schema is structural-only)")
    args = ap.parse_args()
    with locked():
        data = load()
        if args.command == "reserve":
            slug = valid_slug(args.slug); name = args.name or slug
            if not isinstance(name, str) or not name.strip() or len(name) > 200: fail("invalid customer name")
            if slug not in data["customers"]:
                ps, ref = project(slug, name, args)
                data["customers"][slug] = {"slug": slug, "name": name, "status": "reserved", "glitchtip": {"project_slug": ps, "dsn_ref": ref or "secrets/customer-ops/" + slug + "/glitchtip-dsn"}, "portainer": {"status": "pending"}}
            elif normalized_name(name) != normalized_name(data["customers"][slug]["name"]):
                fail("existing slug is reserved for a different customer name")
            validate(data)
            if not args.dry_run: atomic_json(INVENTORY, data)
        elif args.command in ("activate-production", "activate-development"):
            valid_slug(args.slug); c = data["customers"].get(args.slug) or fail("unknown customer")
            details = {"management_target": args.management_target, "node_target": args.node_target, "postgres_target": args.postgres_target, "http_target": args.http_target, "https_target": args.https_target}
            if args.command == "activate-production":
                if not args.name or normalized_name(args.name) != normalized_name(c["name"]): fail("activation name does not match reserved customer")
                validate_domain(args.domain)
                validate_production_targets({**c, "domain": args.domain}, details)
                c["domain"] = args.domain.lower(); c["production"] = dict(active=True, **details); c["status"] = "active"
            else:
                c["development"] = {"active": True, **{k: v for k, v in details.items() if v}}
                c["status"] = "active"
            validate(data)
            if not args.dry_run: atomic_json(INVENTORY, data); reconcile(data) if args.command == "activate-production" else None
        elif args.command == "accept-portainer":
            valid_slug(args.slug); c = data["customers"].get(args.slug) or fail("unknown customer")
            if not REF.fullmatch(args.endpoint_ref) or re.search(r"(?i)(token|password|secret|dsn|api[-_]?key)", args.endpoint_ref): fail("unsafe Portainer endpoint_ref")
            c["portainer"] = {"status": "accepted", "endpoint_ref": args.endpoint_ref}; validate(data)
            if not args.dry_run: atomic_json(INVENTORY, data)
        elif args.command == "reconcile":
            if args.slug: valid_slug(args.slug)
            if args.slug and args.slug not in data["customers"]: fail("unknown customer")
            if args.dry_run:
                validate_rendered_targets(targets(data))
            else:
                reconcile(data)
        elif args.command == "validate":
            validate(data)
    print("ok: " + args.command)

if __name__ == "__main__": main()
