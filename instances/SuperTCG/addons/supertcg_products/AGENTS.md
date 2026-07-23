# AGENTS.md — supertcg_products

Custom Odoo 18 module for SuperTCG. Manages second-hand TCG card intake, buy-in flows, consignment settlement, margin dashboards, and eWallet store credit.

## Deployment & Upgrade

Two Docker environments share the same source via volume mount (`/home/extra-others`):

| Env | Container | Port | Domain |
|-----|-----------|------|--------|
| Dev | `odoo-dev-odoo18-dev-1` | 10019 | dev.supertcg.be |
| Prod | `odoo-one-odoo18-1` | 10018 | supertcg.be |

**Upgrade module (dev):**

```bash
# 1. Validate XML if views changed
python3 -c "import xml.etree.ElementTree as ET; ET.parse('/home/extra-others/supertcg_products/views/YOUR_FILE.xml')"

# 2. Flag for upgrade & restart
docker exec odoo-dev-db-dev-1 psql -U odoo -d odoo -c "UPDATE ir_module_module SET state = 'to upgrade' WHERE name = 'supertcg_products';"
docker restart odoo-dev-odoo18-dev-1
```

Wait ~15–20s for restart. Verify with `curl -s -o /dev/null -w "%{http_code}" http://localhost:10019/web/login` (expect `200`).

**Hard-refresh browser** (Ctrl+Shift+R) after template/JS changes — `dev_mode = reload` is set but cached assets persist.

## Architecture

### Models (`models/`)
- `product_product.py` — Extends `product.product` with `cgs_price`, `bom_price`, `create_tcg_product()` for card creation with image compression.
- `tcg_intake_wizard.py` — Transient wizard for buy-in vs consignment intake.
- `tcg_consignment_settlement.py` — Settlement docs + invoice generation for sold consignment items.
- `tcg_consignment_overview.py` — SQL view model for consignment reporting.
- `tcg_ocr_service.py` — OCR via Google Vision + JustTCG card price lookup.

### Controllers (`controllers/main.py`)
Single `TcgController` with ~25 `@http.route` endpoints. Key pages:
- `/tcg` — Hub dashboard
- `/tcg/aankoop` — Buy-in flow (PO → receipt → vendor bill → payment)
- `/tcg/cards/new` — Card entry form (backed by OWL component)
- `/tcg/consignment` — Consignment settlement UI
- `/tcg/margin` — Margin dashboard with competitor price scraping
- `/tcg/ocr` — OCR card scanner

### Views (`views/`)
QWeb templates for public dashboard pages + standard XML views for backend forms/menus. When editing:
- Escape `&` as `&amp;` and `<` as `&lt;` inside `<script>` blocks in QWeb.
- Always validate XML before upgrading.

### OWL Components (`static/src/`)
- `tcg_card_form/` — Card creation form (camera, bulk mode, product search)
- `tcg_ocr_form/` — OCR scanner + price lookup

Registered in `__manifest__.py` under `assets['web.assets_backend']`.

## Hard-Coded Business Constants

These names are looked up at runtime; changing them requires data migration:

| Concept | Value | Where |
|---------|-------|-------|
| Buy-in product | `"Aankoop 2dehands"` | `_get_or_create_aankoop_product()` |
| Purchase journal | `"Second hand purchases"` | `_get_or_create_secondhand_journal()` |
| Sale tax | `"Margeverkoop"` | `get_default_tcg_taxes()` |
| Purchase tax | `"Margeinkoop"` | `get_default_tcg_taxes()` |

## API Keys & Secrets

- `.env` — `JUSTTCG_API_KEY` for card price lookup (`tcg_ocr_service.py`)
- `google-service-account.json` — Google Vision OCR credentials

Do not commit either file.

## Payment Methods

Buy-in supports three payment methods (sent as `payment_method` string):
- `cash` — Creates `account.payment` via Cash journal, shows POS cash-out warning
- `wire_transfer` — Sends email to `info@supertcg.be`, requires partner bank account
- `store_credit` — Credits eWallet (`loyalty.program` type `ewallet`)

## Consignment Requirements

Consignment tracking requires the `stock.group_tracking_owner` group. If disabled, the flow throws a validation error directing the user to *Inventory → Settings → Consignment*.

## Testing

No automated test suite exists. Verification is manual via the dev instance pages.

## Style & Conventions

- Use Odoo 18 patterns: `@http.route(..., type='json', auth='user')` for API endpoints.
- RPC payloads from frontend use `jsonrpc: '2.0', method: 'call'`.
- Image compression: `_compress_image()` in `product_product.py` resizes to 1920px max and saves as JPEG quality 85.
- `markupsafe.Markup()` is used when posting HTML to chatter.

## Common Pitfalls

1. **XML escaping in QWeb `<script>` blocks** — Raw `&&` or `<` inside inline JS will crash XML parsing. Use `&amp;&amp;` and `&lt;`.
2. **Module not reloading** — `dev_mode = reload` tracks Python file changes but **not** XML/JS/CSS. Always run the upgrade SQL + container restart after view or manifest changes.
3. **Missing tax records** — `Margeverkoop`/`Margeinkoop` taxes must exist in the DB or product creation and buy-in lines fail silently (no tax applied).
4. **eWallet program lookup** — `loyalty.program` with `program_type='ewallet'` is auto-created on first store-credit buy-in if missing.
