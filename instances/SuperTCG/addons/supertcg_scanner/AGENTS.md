# AGENTS.md — SuperTCG Scanner (Odoo 18)

## What this module does

Webhook receiver for Raspberry Pi card scanner sidecars.
- `POST /supertcg/webhook` — receives card batches (auth via per-scanner `X-API-Key`)
- Stores raw card data for review before processing
- Creates products + stock quants directly (no picking)
- Prints ZPL barcode labels via IoT-connected Zebra printers
- Generates buylist PDFs

## Architecture at a glance

```
Pi (scanner) → webhook_controller.py → supertcg.batch
                                          ↓
                    supertcg.batch.card (lines) ← pricing config
                                          ↓
                    product.template + stock.quant + iot label print
```

**Scanner Device** (`supertcg.scanner.device`) is the central mapping: API key → Store (`company_id`) → Warehouse → Location → IoT Printer. The webhook auto-sets batch warehouse/location from this mapping.

## Critical gotchas you will miss without this file

### Odoo 18 IoT runtime patches (non-optional)

The module includes `controllers/iot_patch_controller.py` which inherits from `IoTController` and overrides `/iot/setup` at runtime. This is required because:

1. **Empty MAC (Windows IoT boxes):** `hw_drivers` returns `""` on Windows. Our patch skips MAC search when empty, falls back to IP, and always returns the websocket channel. `_send_zpl_to_iot` also includes `''` in `iotIdentifiers` so the box receives print jobs.
2. **`request.jsonrequest` removed in Odoo 18:** The `iot` module (even in 18.0+e) still uses it. Our patch uses `request.get_json_data()` and handles both JSON-RPC envelopes and raw JSON.

**Never delete `iot_patch_controller.py` — IoT printing will break.**

### `_rec_name` is mandatory on every model

Odoo defaults `_rec_name = 'name'`. Our models use `batch_name`, `card_name`, etc. Missing `_rec_name` causes `display_name` compute to crash with "Replacement index 0 out of range" — breaks MCP, API, and some UI components. Every model in this module already has it; add it to any new model immediately.

### Nginx `/websocket` proxy is required (infrastructure)

Not a code change, but IoT printing will silently fail without it:

```nginx
location /websocket {
    proxy_pass http://odoo:8069/websocket;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;
}
```

After adding this, **restart the IoT box** (`hw_drivers` starts its websocket client exactly once at boot).

### Batch updates merge, not reject

The Pi may resend the same `batch_id`. The webhook merges changes:
- New cards (by `external_product_id`) → created
- Existing cards → only changed fields updated (float tolerance: 0.001)
- Unchanged cards → left alone (preserves user's `is_included` toggle)
- `is_included` and `product_product_id` are **never** overwritten

### Pricing engine (SOP-compliant since v2.0.0)

The pricing config (`supertcg.pricing.config`) implements the full SOP:
- **Purchase:** based on `price_low` (cheapest listing for condition), not `price_market`
- **Condition-based percentages:** NM/EX = 70%, other = 60%, PL/PO = configurable (default 60%)
- **Store credit:** cash % + premium (default +10pp)
- **Sales:** max(market-based markup, category floor price)
- **Category floors:** commons €0.25, holo €1, EX €2.50/€2, VMAX €3, Full Art/Alt Art min €4, WOTC commons €3/€2
- **New set warning:** flags batches with cards from current year

**The Pi sends `condition` in either `condition` or `remark` field.** The webhook maps it to internal codes (`nm`, `ex`, `vg`, `g`, `lp`, `mp`, `hp`, `pl`, `po`, `dmg`). Card category is auto-detected from `rarity`/`printing`/`card_name` and can be manually overridden.

### Ximilar API integration (since v3.0.0)

Every Pi batch automatically spawns a parallel **Ximilar batch** (`supertcg.ximilar.batch`). Card images are sent to the Ximilar TCG identification API (`https://api.ximilar.com/collectibles/v2/tcg_id`) for AI-powered recognition. Results include:
- Card name, set, set_code, card_number, rarity, year
- Foil/holo detection, language, graded slab info
- Price statistics (min, max, mean, median, latest)
- Marketplace links (tcgplayer.com, ebay.com)

Ximilar processing runs in a **separate DB cursor** so webhook responses are not delayed. The Ximilar batch is linked to the source batch via `source_batch_id` and can be opened from the batch form's "Ximilar" stat button.

## Development & deployment

### Install / upgrade
```bash
# Inside Odoo container
odoo -u supertcg_scanner -d your_database --stop-after-init
```

### Docker bytecode caching trap
Odoo containers cache Python bytecode. After model/controller changes, a module upgrade via UI may run old code. **Restart the container** (`docker compose down && up -d`) when changes don't take effect.

### Fresh install XML order
Action records (`<record id="action_..."`) must be defined **before** any menu or view that references them. `supertcg_batch_views.xml` has them at the top for this reason. Breaking this causes `External ID not found` on fresh installs (upgrades are fine because records already exist).

### No tests, no CI, no lint config
This module has no test suite, no GitHub Actions, and no pre-commit/linter configuration. Do not look for them.

## Key files

| File | Purpose |
|------|---------|
| `controllers/webhook_controller.py` | Webhook receiver, batch create/update, CDN image download, direct pricing calc |
| `controllers/iot_patch_controller.py` | **Runtime patch** for Odoo 18 IoT controller (empty MAC, get_json_data) |
| `models/supertcg_batch.py` | Batch model, inventory action, ZPL generation, product/quant creation |
| `models/supertcg_batch_card.py` | Card line model, condition/category detection, SOP pricing compute |
| `models/supertcg_scanner_device.py` | Scanner → Store → Warehouse → Location → Printer mapping |
| `models/supertcg_pricing_config.py` | SOP-compliant pricing config with condition %, floors, slab tiers |
| `models/supertcg_ximilar_batch.py` | Ximilar batch + card models, API integration, price stats parsing |
| `views/supertcg_batch_views.xml` | All views + actions + menus. Action records must come first. |

## Conventions

- Product `type='consu'` with `is_storable=True` (not `product`)
- Barcode = `external_product_id` from Pi
- Taxes: `taxes_id` = "Margeverkoop", `supplier_taxes_id` = "Margeinkoop"
- Label ZPL: 1.5" × 0.5" @ 203dpi (304 × 101 dots). Price on label = `sales_price` (not market).
- `company_id` is labeled "Store" everywhere in UI
- Multi-company record rules exist for batch, batch card, and scanner device

## Issue keywords (search codebase)

Search for `HARDCODE-ISSUE-1` through `HARDCODE-ISSUE-8` to find all workaround comments.
