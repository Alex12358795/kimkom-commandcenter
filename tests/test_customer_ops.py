import copy, importlib.util, json, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/customer-ops.py"
spec = importlib.util.spec_from_file_location("customer_ops", SCRIPT)
ops = importlib.util.module_from_spec(spec); spec.loader.exec_module(ops)

def record(production=True, development=False):
    c = {"slug": "acme", "name": "Acme", "status": "active",
         "glitchtip": {"project_slug": "acme", "dsn_ref": "secrets/customer-ops/acme/glitchtip-dsn"},
         "portainer": {"status": "pending"}}
    if production:
        c["domain"] = "acme.example.com"
        c["production"] = {"active": True, "management_target": "10.0.0.2:9001", "node_target": "10.0.0.2:9100", "postgres_target": "10.0.0.2:9187", "http_target": "http://acme.example.com", "https_target": "https://acme.example.com"}
    if development: c["development"] = {"active": True}
    return {"schema_version": 1, "customers": {"acme": c}}

class CustomerOpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        ops.INVENTORY = root / "operations/customers.json"; ops.LOCK = root / "operations/customers.lock"
        ops.NODE_DIR = root / "prom/node/managed"; ops.BLACKBOX_DIR = root / "prom/blackbox/managed"
        ops.SECRET_ROOT = root / "secrets/customer-ops"
    def tearDown(self): self.tmp.cleanup()

    def test_simultaneous_dev_prod_and_prod_persists(self):
        data = record(development=True); ops.validate(data); before = ops.targets(data)
        self.assertEqual(before["node"][0]["targets"], ["10.0.0.2:9100"])
        data["customers"]["acme"]["development"] = {"active": True, "note": "dev"}
        ops.validate(data); self.assertEqual(ops.targets(data), before)

    def test_reconcile_shape_and_idempotence(self):
        data = record(); ops.validate(data); ops.reconcile(data)
        first = (ops.NODE_DIR / "node.json").read_bytes(); ops.reconcile(data)
        self.assertEqual(first, (ops.NODE_DIR / "node.json").read_bytes())
        payload = json.loads(first); self.assertEqual(set(payload[0]), {"targets", "labels"})
        self.assertEqual(payload[0]["labels"], {"client": "acme", "environment": "production", "managed_by": "kimkom", "domain": "acme.example.com"})

    def test_invalid_slug_is_rejected_before_project_call(self):
        called = []
        old = ops.project; ops.project = lambda *a: called.append(a)
        try:
            with self.assertRaises(SystemExit): ops.valid_slug("../unsafe")
        finally: ops.project = old
        self.assertEqual(called, [])

    def test_existing_slug_name_mismatch_is_rejected_before_project(self):
        data = record(); ops.validate(data); ops.reconcile(data)
        secret = ops.SECRET_ROOT / "acme" / "glitchtip-dsn"; secret.parent.mkdir(parents=True); secret.write_bytes(b"dsn-fixture\n")
        paths = [ops.INVENTORY, secret] + [ops.NODE_DIR / "node.json", ops.NODE_DIR / "postgres.json", ops.BLACKBOX_DIR / "http.json", ops.BLACKBOX_DIR / "https.json"]
        ops.INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        ops.INVENTORY.write_text(json.dumps(data) + "\n")
        before = {p: p.read_bytes() for p in paths}
        called = []
        old = ops.project; ops.project = lambda *a: called.append(a)
        old_argv = sys.argv
        try:
            sys.argv = ["customer-ops.py", "reserve", "acme", "--name", "Another Customer"]
            with self.assertRaises(SystemExit): ops.main()
        finally:
            sys.argv = old_argv; ops.project = old
        self.assertEqual(called, [])
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_activation_name_and_target_identity_rules(self):
        data = record()
        with self.assertRaises(SystemExit):
            ops.validate_production_targets(data["customers"]["acme"], {**data["customers"]["acme"]["production"], "http_target": "http://other.example.com"})
        with self.assertRaises(SystemExit):
            ops.validate_production_targets(data["customers"]["acme"], {**data["customers"]["acme"]["production"], "postgres_target": "10.0.0.3:9187"})

    def test_project_slug_and_dsn_reference_identity(self):
        data = record()
        data["customers"]["acme"]["glitchtip"]["project_slug"] = ""
        with self.assertRaises(SystemExit): ops.validate(data)
        data = record()
        data["customers"]["acme"]["glitchtip"]["dsn_ref"] = "secrets/customer-ops/other/glitchtip-dsn"
        with self.assertRaises(SystemExit): ops.validate(data)

    def test_nonsecret_extra_fields_are_operationally_allowed(self):
        data = record(); data["customers"]["acme"]["owner_note"] = "managed by operations"
        data["customers"]["acme"]["production"]["ticket_ref"] = "OPS-123"
        ops.validate(data)

    def test_schema_acceptance_never_bypasses_operational_validation(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is unavailable")
        schema = json.loads((Path(__file__).parents[1] / "operations/customers.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        invalid = record(); invalid["customers"]["acme"]["glitchtip"]["dsn_ref"] = "secrets/customer-ops/other/glitchtip-dsn"
        self.assertFalse(list(validator.iter_errors(invalid)))
        with self.assertRaises(SystemExit): ops.validate(invalid)

    def test_missing_production_inputs_rejected(self):
        with self.assertRaises(SystemExit): ops.validate_endpoint(None, "node target")
        with self.assertRaises(SystemExit): ops.validate_domain("https://bad.example.com")
        with self.assertRaises(SystemExit): ops.validate_endpoint("https://acme.example.com", "HTTP target", {"http"})

    def test_portainer_requires_nonsecret_endpoint_reference(self):
        data = record(); data["customers"]["acme"]["portainer"] = {"status": "accepted"}
        with self.assertRaises(SystemExit): ops.validate(data)
        data["customers"]["acme"]["portainer"] = {"status": "accepted", "endpoint_ref": "tok-secret"}
        with self.assertRaises(SystemExit): ops.validate(data)

    def test_rejected_input_does_not_change_inventory_or_targets(self):
        data = record(); ops.validate(data); ops.reconcile(data)
        ops.INVENTORY.parent.mkdir(parents=True, exist_ok=True); ops.INVENTORY.write_text(json.dumps(data, sort_keys=True) + "\n")
        secret = ops.SECRET_ROOT / "acme" / "glitchtip-dsn"; secret.parent.mkdir(parents=True); secret.write_bytes(b"dsn-fixture\n")
        paths = [ops.INVENTORY, secret] + [ops.NODE_DIR / "node.json", ops.NODE_DIR / "postgres.json", ops.BLACKBOX_DIR / "http.json", ops.BLACKBOX_DIR / "https.json"]
        before = {p: p.read_bytes() for p in paths}
        for field, value in (("https_target", "https://bad.example.com?token=secret"), ("http_target", "https://acme.example.com"), ("node_target", "10.0.0.3:9100"), ("postgres_target", "10.0.0.3:9187")):
            rejected = copy.deepcopy(data); rejected["customers"]["acme"]["production"][field] = value
            with self.assertRaises(SystemExit): ops.validate(rejected)
            self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_inventory_rejections_preserve_inventory_dsn_and_all_targets(self):
        data = record(); ops.validate(data); ops.reconcile(data)
        ops.INVENTORY.parent.mkdir(parents=True, exist_ok=True); ops.INVENTORY.write_text(json.dumps(data, sort_keys=True) + "\n")
        secret = ops.SECRET_ROOT / "acme" / "glitchtip-dsn"; secret.parent.mkdir(parents=True); secret.write_bytes(b"dsn-fixture\n")
        paths = [ops.INVENTORY, secret] + [ops.NODE_DIR / "node.json", ops.NODE_DIR / "postgres.json", ops.BLACKBOX_DIR / "http.json", ops.BLACKBOX_DIR / "https.json"]
        before = {p: p.read_bytes() for p in paths}
        invalids = []
        for key, value in (("project_slug", ""), ("dsn_ref", "secrets/customer-ops/other/glitchtip-dsn")):
            candidate = copy.deepcopy(data); candidate["customers"]["acme"]["glitchtip"][key] = value; invalids.append(candidate)
        candidate = copy.deepcopy(data); candidate["customers"]["acme"]["notes"] = {"api_token": "do-not-store"}; invalids.append(candidate)
        for candidate in invalids:
            with self.assertRaises(SystemExit): ops.validate(candidate)
            self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_schema_rejects_structural_invalid_records(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is unavailable")
        schema = json.loads((Path(__file__).parents[1] / "operations/customers.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema)
        self.assertFalse(list(validator.iter_errors(record())))
        invalid = copy.deepcopy(record()); invalid["customers"]["acme"]["production"]["active"] = "yes"
        self.assertTrue(list(validator.iter_errors(invalid)))
        invalid = copy.deepcopy(record()); invalid["customers"]["acme"]["portainer"] = "pending"
        self.assertTrue(list(validator.iter_errors(invalid)))

    def test_dry_run_reconcile_leaves_inventory_and_targets_unchanged(self):
        data = record(); ops.validate(data); ops.reconcile(data)
        ops.INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        ops.INVENTORY.write_text(json.dumps(data, sort_keys=True) + "\n")
        old_target = (ops.NODE_DIR / "node.json").read_bytes()
        old_inventory = ops.INVENTORY.read_bytes()
        old_argv = sys.argv
        try:
            sys.argv = ["customer-ops.py", "--dry-run", "reconcile"]
            ops.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(old_target, (ops.NODE_DIR / "node.json").read_bytes())
        self.assertEqual(old_inventory, ops.INVENTORY.read_bytes())

if __name__ == "__main__": unittest.main()
