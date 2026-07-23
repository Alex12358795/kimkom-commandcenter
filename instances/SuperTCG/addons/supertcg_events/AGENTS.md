# SuperTCG Events — Agent Notes

Odoo 18 custom module for SuperTCG (Belgian trading card game store chain). Adds recurring weekly events, waitlist, POS barcodes, Pay at Venue, and location landing pages.

## Dev Environment

- Docker Compose lives at `/home/odoo-dev/`. Module source is `/home/extra-others/supertcg_events/`.
- Odoo runs in container `odoo18-dev`, DB in `db-dev` (PostgreSQL 17).
- Database name: `odoo`. Admin password: `adminpassword`.
- Web: `https://dev.supertcg.be` (proxied), direct: `http://localhost:10019`.
- Log file inside container: `/etc/odoo/odoo-server.log`.

### Restart / Upgrade Module

```bash
cd /home/odoo-dev

# Restart container to pick up Python changes
docker compose restart odoo18-dev

# Upgrade module (required after XML/view changes)
docker compose exec odoo18-dev odoo \
  --db_host=db-dev --db_port=5432 \
  --db_user=odoo --db_password=odoo18@2024 \
  -u supertcg_events -d odoo \
  --stop-after-init --no-http

# Restart again after --stop-after-init
docker compose restart odoo18-dev
```

**Restart alone is NOT enough for XML/view changes** — you must run the upgrade command above.

## Critical Production Gotchas

### 1. `doc_name` Field from `atharva_theme_base`

Production has `atharva_theme_base` installed. It adds a **required translated Char field `doc_name`** on `product.template`.

During module upgrades, this field exists in the DB schema but is NOT yet in Odoo's `_fields` registry (because `atharva_theme_base` is not a dependency). Product creation fails with either:
- `null value in column "doc_name"`
- `Invalid field 'doc_name' on model 'product.product'`

**Fix**: `_create_product_with_doc_name_fallback()` in `models/event_ticket_barcode.py` detects this by checking `information_schema.columns` directly, temporarily sets a PostgreSQL default, creates the product, then drops the default.

**Never remove this workaround.** If `atharva_theme_base` changes its field requirements, update the fallback logic.

### 2. No Savepoints in Web Request Context

Odoo's HTTP framework manages savepoints internally for transaction retry logic. Using `with request.env.cr.savepoint():` or raw SQL `SAVEPOINT`/`ROLLBACK TO SAVEPOINT` inside controllers or model methods called during web requests causes `InvalidSavepointSpecification`.

**Rule**: Never use manual savepoints in code paths reachable from HTTP controllers. Let Odoo handle rollback on exceptions.

### 3. `event.event_subscription` is `noupdate="1"`

The standard event confirmation email template is marked `noupdate`. XML data file overrides **do not update** existing records during module upgrades.

**Fix**: Update via raw SQL on the `body_html` JSONB column in migration scripts. See `migrations/1.2.4/post-migrate.py` for the working pattern.

### 4. Public Users Cannot Read `res.partner`

Odoo's `res_partner_portal_public_rule` restricts public/portal users to only their own commercial partner. Accessing `event.address_id.name` (or any `res.partner` field) in a public controller throws 403.

**Fix**: Use `sudo()` in the controller to read partner data, extract plain string values into a dict, and pass only the dict to the template. See `controllers/main.py` (`events_locations`, `events_by_location`) for the pattern.

## Architecture

### Models

| File | Purpose |
|------|---------|
| `models/event_event.py` | Event extensions: recurring templates, weekly copies via cron, `_auto_init()` safety net |
| `models/event_waitlist.py` | Waitlist model with states |
| `models/event_registration.py` | Registration extensions: `payment_status`, `pay_at_venue` |
| `models/event_ticket_barcode.py` | POS barcode generation, product creation, `doc_name` workaround, `_auto_init()` |

### Key Features

- **Recurring events**: Events in "Recurring Template" stage get auto-copied weekly via cron (`_cron_generate_weekly_events`).
- **POS barcodes**: Each paid ticket gets a unique `product.product` with an EAN-13 barcode. Staff scan at POS like any product — no POS JS modifications.
- **Pay at Venue**: Attendees register online, pay at store. Registration gets `pay_at_venue=True` and `payment_status='pending'`. Confirmation email shows the POS barcode.
- **Location pages**: `/events/locations` and `/events/location/<slug>` — public landing pages grouped by store.

### `_auto_init()` Safety Net

All models with new columns override `_auto_init()` to recreate missing columns. This makes the module self-healing if migrations fail partway.

## Migration Pattern

- Bump version in `__manifest__.py` to trigger migrations.
- Create folder: `migrations/<version>/post-migrate.py` (or `pre-migrate.py`).
- For JSONB translated fields (like `mail_template.body_html`): use **raw SQL**, not ORM `write()`. The ORM does not reliably persist JSONB changes during migrations.
- Pre-migration scripts that alter schema should use `cr.commit()` to separate schema changes from data operations.

## Language

User-facing text is **Dutch (nl_BE)**. Always wrap user-facing strings with `_()` for translation support.

## Dependencies

Standard Odoo: `event`, `event_sale`, `website`, `website_event`.

Third-party modules installed in the environment (do NOT add as dependencies):
- `atharva_theme_base` — adds `doc_name` required field on `product.template`
- `product_barcode` — auto-generates barcodes on `product.product.create()`
- `common_connector_library` — overrides `product.template.create()`

## Files Worth Knowing

| File | What it does |
|------|--------------|
| `__manifest__.py` | Module metadata, version, dependencies, data files |
| `__init__.py` | `post_init_hook`: generates barcodes + updates mail template on install |
| `controllers/main.py` | Web routes: locations, waitlist, Pay at Venue registration |
| `data/ir_cron_data.xml` | Weekly event copy cron job |
| `security/ir.model.access.csv` | Waitlist ACL for public/portal/user/manager |
| `security/security_rules.xml` | Waitlist record rules (public sees own by email) |
| `migrations/1.2.4/post-migrate.py` | Reference pattern for raw SQL JSONB updates + product category fix |
