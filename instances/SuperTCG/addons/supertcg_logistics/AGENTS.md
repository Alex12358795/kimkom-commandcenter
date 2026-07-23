# SuperTCG Logistics — Agent Notes

## What This Is

An **Odoo 18 addon module** (`supertcg_logistics`) that enables multi-warehouse stock aggregation for the SuperTCG e-commerce website. It lives at `/home/extra-others/supertcg_logistics/`.

## Hardcoded Data (Do Not Change Without User Approval)

| ID | Warehouse | Purpose |
|---|---|---|
| 5 | Leuven 122 | Physical store |
| 6 | Leuven 49 | Physical store |
| 7 | Mechelen | Physical store |
| 8 | Hasselt | Physical store |

These IDs are baked into `models/*.py`. Changing them breaks stock calculations.

## How to Run Tests

Tests are **standalone Python scripts**, not pytest/unittest:

```bash
# Backend logic tests
docker exec odoo-dev-odoo18-dev-1 python3 /home/extra-others/supertcg_logistics/tests/test_supertcg_logistics.py

# Full e2e flow simulation (creates real sale orders, commits, cleans up)
docker exec odoo-dev-odoo18-dev-1 python3 /home/extra-others/supertcg_logistics/tests/test_full_flow.py
```

Both scripts print `PASS/FAIL` lines and exit 0/1.

## Critical Dev Environment Fix

The Docker entrypoint (`/home/odoo-dev/entrypoint.sh`) was patched to pass `-c "$ODOO_RC"` and `--dev=reload`. Without this, Odoo ignores `dev_mode = reload` from the config file because Odoo's `config.py` **always overwrites** `dev_mode` with the `--dev` CLI option (resetting to `[]` if not passed).

**Do NOT revert the entrypoint.** The running process must show:
```
odoo -c /etc/odoo/odoo.conf --dev=reload ...
```

## Post-Restore SQL Fixes (Required After Each Prod Restore)

After restoring production DB to dev, run these SQL fixes before testing:

```sql
-- Set website warehouse (empty = "All warehouses" in production)
UPDATE website SET warehouse_id = NULL WHERE id = 1;

-- Activate carriers
UPDATE delivery_carrier SET active = true WHERE id IN (1, 4);

-- Enable payment providers
UPDATE payment_provider SET state = 'enabled' WHERE id = 15;
UPDATE payment_provider SET state = 'test' WHERE id = 6;

-- Ensure all 4 stores linked to pickup carrier
INSERT INTO delivery_carrier_stock_warehouse_rel (delivery_carrier_id, stock_warehouse_id)
SELECT 4, 8 WHERE NOT EXISTS (
    SELECT 1 FROM delivery_carrier_stock_warehouse_rel
    WHERE delivery_carrier_id = 4 AND stock_warehouse_id = 8
);
```

## Architecture Quirks

### Method Signature Pitfall

When overriding `Website._get_product_available_qty()`, use `**kwargs` passthrough (like `website_sale_collect` does). Passing `website` as a positional arg to `super()` crashes because the parent signature only accepts `self, product`:

```python
# WRONG — causes TypeError
def _get_product_available_qty(self, product, website=None):
    return super()._get_product_available_qty(product, website)

# CORRECT
def _get_product_available_qty(self, product, **kwargs):
    return super()._get_product_available_qty(product, **kwargs)
```

### Warehouse Routing

`suggested_warehouse_id` on `sale.order.line` is **computed only** — it does NOT auto-route the order. The order's `warehouse_id` must be explicitly set (e.g., in `_cart_update`) to ensure pickings are created from the correct store.

### `_cart_update` Parameter Trap

`set_qty` arrives as `None` from web forms when clicking "Add to Cart". Always normalize before comparison:

```python
if set_qty is not None:
    set_qty = float(set_qty)
else:
    set_qty = 0
```

### Delivery Cost Multiplier

`_create_delivery_line` multiplies the carrier price by the number of unique warehouses across order lines. This affects **both** web and backend orders.

## Module Deployment

1. Copy `/home/extra-others/supertcg_logistics/` to production addons path
2. Restart Odoo or use `-u supertcg_logistics` to upgrade
3. No entrypoint changes needed on production (`dev_mode` is commented out in prod)

## Files That Matter

| File | Purpose |
|---|---|
| `__manifest__.py` | Module metadata, version, dependencies |
| `models/sale_order.py` | Cart update logic, delivery multiplier, warehouse routing |
| `models/website.py` | Stock aggregation across 4 warehouses |
| `models/sale_order_line.py` | `suggested_warehouse_id` computed field |
| `models/product_product.py` | Add-to-cart possibility, per-warehouse availability |
| `views/product_templates.xml` | "Available in" box on product page |
| `tests/test_full_flow.py` | End-to-end validation (order → picking → invoice) |
| `tests/test_supertcg_logistics.py` | Backend unit tests |
| `/home/odoo-dev/entrypoint.sh` | **Patched** — critical for dev reload |

## What NOT to Touch

- Do NOT restart production Odoo without explicit user approval
- Do NOT change warehouse IDs (5,6,7,8) without checking all model references
- Do NOT add `--dev=reload` to production entrypoint
