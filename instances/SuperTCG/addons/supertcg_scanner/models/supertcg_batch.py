import base64
import json
import logging
import time
import urllib.request

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


# HARDCODE-ISSUE-5: _rec_name defaults to 'name' but this model uses 'batch_name'.
# Missing _rec_name causes display_name compute to crash with string formatting errors.
class SuperTCGBatch(models.Model):
    _name = 'supertcg.batch'
    _description = 'SuperTCG Scanner Batch'
    _order = 'scanned_at desc, id desc'
    _inherit = ['mail.thread']
    _rec_name = 'batch_name'

    # ─── Identification ───
    batch_id = fields.Char(
        string='Batch ID',
        required=True,
        index=True,
        copy=False,
        help='Unique external identifier from the scanner sidecar',
    )
    batch_name = fields.Char(
        string='Batch Name',
        required=True,
    )
    batch_type = fields.Selection(
        selection=[
            ('inventory', 'Inventory'),
            ('buylist', 'Buylist'),
        ],
        string='Batch Type',
        required=True,
        default='inventory',
    )

    # ─── Timing & Source ───
    scanned_at = fields.Datetime(
        string='Scanned At',
        help='When the batch was saved on the scanner device',
    )
    device_id = fields.Char(
        string='Device ID',
        help='Identifier of the scanning station (e.g., raspberry-pi-5-super tcg)',
    )

    # ─── Counts ───
    card_count = fields.Integer(
        string='Card Count',
        default=0,
    )
    included_card_count = fields.Integer(
        string='Included Cards',
        compute='_compute_included_card_count',
        store=True,
    )
    excluded_card_count = fields.Integer(
        string='Excluded Cards',
        compute='_compute_included_card_count',
        store=True,
    )

    # ─── State ───
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('processed', 'Processed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        tracking=True,
    )

    # ─── Inventory Location (auto-set from scanner device mapping) ───
    scanner_device_id = fields.Many2one(
        'supertcg.scanner.device',
        string='Scanner',
        readonly=True,
        help='Scanner device that created this batch — set automatically from API key',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        readonly=True,
        help='Warehouse where inventory will be added — set automatically from scanner mapping',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        readonly=True,
        help='Stock location for inventory receipt — set automatically from scanner mapping',
    )

    # ─── Relations ───
    card_line_ids = fields.One2many(
        'supertcg.batch.card',
        'batch_id',
        string='Cards',
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Created Products',
        compute='_compute_product_ids',
        store=False,
    )

    # ─── Raw Data ───
    raw_payload = fields.Json(
        string='Raw Payload',
        help='Complete original JSON payload from the webhook',
    )
    notes = fields.Text(
        string='Notes',
        help='Internal notes about this batch',
    )

    # ─── Multi-Company ───
    company_id = fields.Many2one(
        'res.company',
        string='Store',
        default=lambda self: self.env.company,
        required=True,
    )

    # ─── Product Categories ───
    product_category_id = fields.Many2one(
        'product.category',
        string='Internal Category',
        help='Override the default category (which is based on game name).',
    )
    website_category_ids = fields.Many2many(
        'product.public.category',
        string='Website Categories',
        help='Categories where the product will appear on the website shop.',
    )

    # ─── Computed Totals ───
    total_market_price = fields.Float(
        string='Total Market Price',
        compute='_compute_totals',
        store=True,
        digits=(16, 2),
    )
    total_purchase_price = fields.Float(
        string='Total Purchase Price (Cash/Wire Transfer)',
        compute='_compute_totals',
        store=True,
        digits=(16, 2),
    )
    total_credit_purchase_price = fields.Float(
        string='Total Store Credit Purchase Price',
        compute='_compute_totals',
        store=True,
        digits=(16, 2),
    )
    has_new_set_cards = fields.Boolean(
        string='Has New Set Cards',
        compute='_compute_has_new_set_cards',
        store=True,
        help='True if any card in this batch is from a recently released set.',
    )

    # ─── Logs ───
    log_ids = fields.One2many(
        'supertcg.batch.log',
        'batch_id',
        string='Processing Logs',
        readonly=True,
    )

    # ─── Constraints ───
    _sql_constraints = [
        ('batch_id_unique', 'UNIQUE(batch_id)', 'Batch ID must be unique!'),
    ]

    # ─── Logging Helper ───
    def log(self, message, level='info', stage=None):
        """Add a processing log entry to this batch."""
        self.ensure_one()
        return self.env['supertcg.batch.log'].sudo().create({
            'batch_id': self.id,
            'level': level,
            'stage': stage,
            'message': message,
        })

    @api.depends('batch_name', 'batch_id')
    def _compute_display_name(self):
        for batch in self:
            # Avoid showing "Unsaved Batch" — fall back to batch_id or ID
            if batch.batch_name and batch.batch_name != 'Unsaved Batch':
                name = batch.batch_name
            elif batch.batch_id:
                name = batch.batch_id
            else:
                name = f"Batch {batch.id}"
            batch.display_name = name

    def name_get(self):
        """Override to avoid 'Unsaved Batch' in lists, search, and references."""
        result = []
        for batch in self:
            if batch.batch_name and batch.batch_name != 'Unsaved Batch':
                name = batch.batch_name
            elif batch.batch_id:
                name = batch.batch_id
            else:
                name = f"Batch {batch.id}"
            result.append((batch.id, name))
        return result

    # ─── Compute Methods ───
    @api.depends('card_line_ids.is_included')
    def _compute_included_card_count(self):
        for batch in self:
            included = batch.card_line_ids.filtered(lambda c: c.is_included)
            batch.included_card_count = len(included)
            batch.excluded_card_count = len(batch.card_line_ids) - len(included)

    @api.depends('card_line_ids.product_product_id')
    def _compute_product_ids(self):
        for batch in self:
            batch.product_ids = batch.card_line_ids.mapped('product_product_id')

    @api.depends('card_line_ids.price_market', 'card_line_ids.purchase_price', 'card_line_ids.credit_purchase_price', 'card_line_ids.is_included')
    def _compute_totals(self):
        for batch in self:
            included = batch.card_line_ids.filtered(lambda c: c.is_included)
            batch.total_market_price = sum(included.mapped('price_market') or [0.0])
            batch.total_purchase_price = sum(included.mapped('purchase_price') or [0.0])
            batch.total_credit_purchase_price = sum(included.mapped('credit_purchase_price') or [0.0])

    @api.depends('card_line_ids.is_new_set')
    def _compute_has_new_set_cards(self):
        for batch in self:
            batch.has_new_set_cards = any(batch.card_line_ids.mapped('is_new_set'))

    # ─── Actions ───
    def action_add_to_inventory(self):
        """Create products for included cards, add stock quants, and print labels."""
        self.ensure_one()
        self.log("Starting inventory intake", level='info', stage='inventory_start')

        if self.state != 'draft':
            self.log("Batch is not in draft state (state=%s)" % self.state, level='error', stage='inventory_start')
            raise UserError(_("Only draft batches can be added to inventory."))
        if not self.scanner_device_id:
            self.log("No scanner device linked to this batch", level='error', stage='inventory_start')
            raise UserError(_("This batch has no scanner device linked. It may have been created manually."))
        if not self.warehouse_id or not self.location_id:
            self.log("Scanner device has no warehouse/location configured", level='error', stage='inventory_start')
            raise UserError(_("The scanner device for this batch has no warehouse or location configured. Please update the scanner device mapping."))
        if not self.product_category_id:
            self.log("No internal category selected", level='error', stage='inventory_start')
            raise UserError(_("Please select an Internal Category before adding to inventory."))

        included_cards = self.card_line_ids.filtered(lambda c: c.is_included)
        if not included_cards:
            self.log("No cards selected for inventory", level='warning', stage='inventory_start')
            raise UserError(_("No cards are selected for inventory. Please include at least one card."))

        self.log("Processing %s cards at %s" % (len(included_cards), self.location_id.display_name), level='info', stage='inventory_start')

        # Process in the batch's company context
        self = self.with_company(self.company_id)

        product_cache = {}
        processed = 0
        errors = 0

        for card in included_cards:
            try:
                self.log("Creating product for card: %s (ID: %s)" % (card.card_name, card.external_product_id), level='info', stage='product_create')
                product = self._get_or_create_product(card, product_cache)
                if product:
                    card.product_product_id = product.id
                    self.log("Product created: %s (ID: %s, Barcode: %s)" % (product.name, product.id, product.barcode), level='success', stage='product_create')
                    # Update stock quant at selected location
                    self.env['stock.quant']._update_available_quantity(
                        product, self.location_id, 1.0
                    )
                    self.log("Stock quant updated: +1 at %s" % self.location_id.display_name, level='success', stage='stock_quant')
                    processed += 1
            except Exception as e:
                self.log("Error processing card %s: %s" % (card.card_name, str(e)), level='error', stage='product_create')
                _logger.error("Error processing card %s in batch %s: %s", card.card_name, self.batch_id, str(e))
                errors += 1

        self.write({'state': 'processed'})
        self.log("Inventory intake complete — %s processed, %s errors" % (processed, errors), level='success', stage='inventory_complete')

        # Reload the form so buttons update for the new state
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'views': [[False, 'form']],
            'res_id': self.id,
            'target': 'current',
        }

    def action_generate_buylist_pdf(self):
        """Print the buylist PDF report for this batch."""
        self.ensure_one()
        self.log("Generating buylist PDF for %s cards" % self.included_card_count, level='info', stage='buylist_pdf')
        return self.env.ref('supertcg_scanner.action_report_buylist').report_action(self)

    # ─── Navigation ───
    def action_open_all_cards(self):
        """Open the All Cards list view."""
        return self.env.ref('supertcg_scanner.action_supertcg_batch_card').read()[0]

    def action_open_label_mappings(self):
        """Open the Scanner → Devices view."""
        return self.env.ref('supertcg_scanner.action_supertcg_scanner_device').read()[0]

    def action_open_pricing(self):
        """Open the Pricing Formula view."""
        return self.env.ref('supertcg_scanner.action_supertcg_pricing_config').read()[0]

    def action_pull_from_pi(self):
        """Pull latest batches from all configured Pi status servers."""
        devices = self.env["supertcg.scanner.device"].sudo().search([
            ("active", "=", True),
            ("pi_url", "!=", False),
        ])

        if not devices:
            raise UserError(_("No active scanner devices with a Pi URL configured. Please set the Pi URL in Scanner → Devices."))

        total_created = 0
        total_skipped = 0
        errors = []

        for device in devices:
            pi_url = device.pi_url
            api_key = device.api_key

            if not pi_url or not api_key:
                errors.append(_("%(device)s: missing Pi URL or API key") % {"device": device.name})
                continue

            try:
                req = urllib.request.Request(
                    pi_url,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": api_key,
                    },
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                errors.append(_("%(device)s: HTTP %(code)s") % {"device": device.name, "code": e.code})
                continue
            except urllib.error.URLError as e:
                errors.append(_("%(device)s: cannot connect (%(reason)s)") % {"device": device.name, "reason": e.reason})
                continue
            except json.JSONDecodeError:
                errors.append(_("%(device)s: invalid JSON response") % {"device": device.name})
                continue

            if not data.get("ok"):
                errors.append(_("%(device)s: Pi error — %(error)s") % {"device": device.name, "error": data.get("error", "Unknown")})
                continue

            batches = data.get("batches", [])
            for batch_data in batches:
                batch_id = batch_data.get("batch_id")
                if not batch_id:
                    continue

                existing = self.search([("batch_id", "=", batch_id)], limit=1)

                # Parse scanned_at
                scanned_at_raw = batch_data.get("scanned_at")
                scanned_at = False
                if scanned_at_raw:
                    from datetime import datetime, timezone, timedelta
                    try:
                        dt = datetime.fromisoformat(str(scanned_at_raw).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone(timedelta(hours=2)))
                        scanned_at = dt.astimezone(timezone.utc).replace(tzinfo=None)
                    except (ValueError, TypeError):
                        scanned_at = False

                if existing:
                    # Update existing batch (merge cards like webhook does)
                    self._update_batch_from_pi(existing, batch_data, scanned_at, device)
                    total_skipped += 1
                    continue

                batch_vals = {
                    "batch_id": batch_id,
                    "batch_name": batch_data.get("batch_name") or batch_id,
                    "batch_type": "inventory",
                    "scanned_at": scanned_at,
                    "device_id": batch_data.get("device_id", ""),
                    "card_count": batch_data.get("card_count", 0),
                    "company_id": device.company_id.id,
                    "scanner_device_id": device.id,
                    "warehouse_id": device.warehouse_id.id if device.warehouse_id else False,
                    "location_id": device.location_id.id if device.location_id else False,
                }

                batch = self.sudo().create(batch_vals)

                # Create card lines
                for card_data in batch_data.get("cards", []):
                    self._create_card_line_from_pi(batch, card_data)

                total_created += 1

        # Build result message
        messages = []
        if total_created:
            messages.append(_("Imported %s batch(es).") % total_created)
        if total_skipped:
            messages.append(_("Updated %s existing batch(es).") % total_skipped)
        if errors:
            messages.append(_("Errors: %s") % "; ".join(errors))

        # Show notification and reload the form view so new cards appear
        notification = {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Pull Complete"),
                "message": "\n".join(messages) if messages else _("No new batches available."),
                "type": "success" if (total_created or total_skipped) and not errors else "warning" if errors else "info",
                "sticky": True if errors else False,
            },
        }

        # If called from a specific batch record, reload the form to show new cards
        if self and len(self) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": self._name,
                "views": [[False, "form"]],
                "res_id": self.id,
                "target": "current",
                "context": {"notification": notification},
            }

        return notification

    def _create_card_line_from_pi(self, batch, card_data):
        """Create a single card line from Pi pull response (reuses webhook logic)."""
        _parse_float = lambda val: float(val) if val not in (None, "", False) else 0.0
        _parse_int = lambda val: int(val) if val not in (None, "", False) else 0
        _parse_bool = lambda val: str(val).strip().lower() == "true"

        CardModel = batch.env["supertcg.batch.card"]
        raw_condition = str(card_data.get("condition", "") or card_data.get("remark", "") or "")
        condition = CardModel.map_condition(raw_condition)
        card_category = CardModel.detect_card_category(card_data)

        vals = {
            "batch_id": batch.id,
            "scanner_alias": str(card_data.get("scanner", "") or ""),
            "sequence": _parse_int(card_data.get("seq") or card_data.get("cursor")),
            "timestamp": str(card_data.get("timestamp", "") or ""),
            "remark": raw_condition,
            "condition": condition,
            "card_category": card_category,
            "card_name": str(card_data.get("card_name", "") or ""),
            "clean_name": str(card_data.get("clean_name", "") or ""),
            "card_number": str(card_data.get("card_number", "") or ""),
            "set_code": str(card_data.get("set_code", "") or ""),
            "set_name": str(card_data.get("set_name", "") or ""),
            "external_product_id": str(card_data.get("product_id", "") or ""),
            "rarity": str(card_data.get("rarity", "") or ""),
            "printing": str(card_data.get("printing", "") or ""),
            "language": str(card_data.get("language", "") or ""),
            "foil": _parse_bool(card_data.get("foil")),
            "is_reverse_holo": _parse_bool(card_data.get("is_reverse_holo")),
            "price_low": _parse_float(card_data.get("price_low")),
            "price_mid": _parse_float(card_data.get("price_mid")),
            "price_high": _parse_float(card_data.get("price_high")),
            "price_market": _parse_float(card_data.get("price_market")),
            "price_direct_low": _parse_float(card_data.get("price_direct_low")),
            "purchase_basis": _parse_float(card_data.get("price_low")),
            "cdn_image_url": str(card_data.get("cdn_image", "") or card_data.get("cdn_image_url", "") or ""),
            "company_id": batch.company_id.id,
            # Extended fields
            "ext_card_type": str(card_data.get("ext_card_type", "") or ""),
            "ext_hp": str(card_data.get("ext_hp", "") or ""),
            "ext_stage": str(card_data.get("ext_stage", "") or ""),
            "ext_cardtext": str(card_data.get("ext_cardtext", "") or ""),
            "ext_attack_1": str(card_data.get("ext_attack_1", "") or ""),
            "ext_attack_2": str(card_data.get("ext_attack_2", "") or ""),
            "ext_weakness": str(card_data.get("ext_weakness", "") or ""),
            "ext_resistance": str(card_data.get("ext_resistance", "") or ""),
            "ext_retreatcost": str(card_data.get("ext_retreatcost", "") or ""),
        }

        # Handle product_id / external_product_id
        product_id_val = card_data.get("product_id", "")
        if product_id_val is not None:
            vals["external_product_id"] = str(product_id_val)

        # Image download
        cdn_url = card_data.get("cdn_image", "") or card_data.get("cdn_image_url", "")
        if cdn_url:
            try:
                req = urllib.request.Request(cdn_url, headers={"User-Agent": "SuperTCG-Scanner/1.0"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    img_data = response.read()
                    if img_data:
                        vals["image_base64"] = base64.b64encode(img_data).decode("ascii")
            except Exception as img_err:
                _logger.warning("Failed to download image from %s: %s", cdn_url, img_err)

        # Pricing calculation
        purchase_basis = vals.get("purchase_basis") or vals.get("price_market") or 0.0
        if purchase_basis:
            try:
                config = batch.env["supertcg.pricing.config"].get_config(batch.company_id)
                if config:
                    cash_pct = config.get_purchase_pct(condition)
                    credit_pct = config.get_credit_purchase_pct(condition)
                    increment = float(config.round_to)

                    purchase = round((purchase_basis * cash_pct / 100.0) / increment) * increment
                    purchase = max(purchase, config.purchase_min_price)

                    credit = round((purchase_basis * credit_pct / 100.0) / increment) * increment
                    credit = max(credit, config.purchase_min_price)

                    market = vals.get("price_market", 0.0)
                    market_based = round((market * config.sales_markup_pct / 100.0) / increment) * increment
                    market_based = max(market_based, config.sales_min_price)

                    lang = str(vals.get("language", "") or "").lower()
                    floor = config.get_sales_floor(card_category, False, condition, lang)
                    sales = max(market_based, floor)

                    vals["purchase_price"] = purchase
                    vals["credit_purchase_price"] = credit
                    vals["sales_price"] = sales
            except Exception as price_err:
                _logger.warning("Failed to calculate pricing for card %s: %s", vals.get("card_name"), price_err)

        batch.env["supertcg.batch.card"].sudo().create(vals)

    def _update_batch_from_pi(self, batch, batch_data, scanned_at, device):
        """Update an existing batch with new/changed cards from Pi pull.
        
        Mirrors webhook _update_batch logic: merges cards, updates metadata.
        """
        batch_id = batch.batch_id
        _logger.info("SuperTCG pull: updating existing batch %s", batch_id)

        # Update batch metadata
        batch.write({
            "batch_name": batch_data.get("batch_name") or batch.batch_name,
            "scanned_at": scanned_at or batch.scanned_at,
            "device_id": batch_data.get("device_id", batch.device_id),
            "card_count": batch_data.get("card_count", 0),
        })

        # Build index of existing cards by external_product_id for fast lookup
        existing_cards = {
            card.external_product_id: card
            for card in batch.card_line_ids
            if card.external_product_id
        }

        created = 0
        updated = 0
        unchanged = 0

        for card_data in batch_data.get("cards", []):
            product_id = str(card_data.get("product_id", "") or "")
            existing_card = existing_cards.get(product_id) if product_id else None

            if existing_card:
                changed = self._update_card_line_from_pi(batch, existing_card, card_data)
                if changed:
                    updated += 1
                else:
                    unchanged += 1
            else:
                self._create_card_line_from_pi(batch, card_data)
                created += 1

        # Recalculate totals
        batch.write({"card_count": len(batch.card_line_ids)})
        batch.env.cr.flush()

        _logger.info(
            "SuperTCG pull: batch %s update complete. Created: %s, Updated: %s, Unchanged: %s",
            batch_id, created, updated, unchanged
        )

    def _update_card_line_from_pi(self, batch, card, card_data):
        """Update an existing card line with only changed fields from Pi pull.
        
        Returns True if any field was actually changed, False otherwise.
        Never touches is_included or product_product_id — those are user-managed.
        """
        _parse_float = lambda val: float(val) if val not in (None, "", False) else 0.0
        _parse_int = lambda val: int(val) if val not in (None, "", False) else 0
        _parse_bool = lambda val: str(val).strip().lower() == "true"

        CardModel = batch.env["supertcg.batch.card"]
        raw_condition = str(card_data.get("condition", "") or card_data.get("remark", "") or "")
        new_condition = CardModel.map_condition(raw_condition)
        new_category = CardModel.detect_card_category(card_data)

        # Fields that can be updated from the Pi
        updatable_fields = {
            "scanner_alias": str(card_data.get("scanner", "") or ""),
            "sequence": _parse_int(card_data.get("seq") or card_data.get("cursor")),
            "timestamp": str(card_data.get("timestamp", "") or ""),
            "remark": raw_condition,
            "condition": new_condition,
            "card_category": new_category,
            "card_name": str(card_data.get("card_name", "") or ""),
            "clean_name": str(card_data.get("clean_name", "") or ""),
            "card_number": str(card_data.get("card_number", "") or ""),
            "set_code": str(card_data.get("set_code", "") or ""),
            "set_name": str(card_data.get("set_name", "") or ""),
            "external_product_id": str(card_data.get("product_id", "") or ""),
            "rarity": str(card_data.get("rarity", "") or ""),
            "printing": str(card_data.get("printing", "") or ""),
            "language": str(card_data.get("language", "") or ""),
            "foil": _parse_bool(card_data.get("foil")),
            "is_reverse_holo": _parse_bool(card_data.get("is_reverse_holo")),
            "price_low": _parse_float(card_data.get("price_low")),
            "price_mid": _parse_float(card_data.get("price_mid")),
            "price_high": _parse_float(card_data.get("price_high")),
            "price_market": _parse_float(card_data.get("price_market")),
            "price_direct_low": _parse_float(card_data.get("price_direct_low")),
            "purchase_basis": _parse_float(card_data.get("price_low")),
            "cdn_image_url": str(card_data.get("cdn_image", "") or card_data.get("cdn_image_url", "") or ""),
            # Extended fields
            "ext_card_type": str(card_data.get("ext_card_type", "") or ""),
            "ext_hp": str(card_data.get("ext_hp", "") or ""),
            "ext_stage": str(card_data.get("ext_stage", "") or ""),
            "ext_cardtext": str(card_data.get("ext_cardtext", "") or ""),
            "ext_attack_1": str(card_data.get("ext_attack_1", "") or ""),
            "ext_attack_2": str(card_data.get("ext_attack_2", "") or ""),
            "ext_weakness": str(card_data.get("ext_weakness", "") or ""),
            "ext_resistance": str(card_data.get("ext_resistance", "") or ""),
            "ext_retreatcost": str(card_data.get("ext_retreatcost", "") or ""),
        }

        # Check which fields actually changed
        write_vals = {}
        for field_name, new_value in updatable_fields.items():
            old_value = getattr(card, field_name, None)
            # Handle float comparison with tolerance
            if isinstance(new_value, float) and isinstance(old_value, float):
                if abs(new_value - old_value) > 0.001:
                    write_vals[field_name] = new_value
            elif new_value != old_value:
                write_vals[field_name] = new_value

        # Handle image — only update if new image provided
        cdn_url = card_data.get("cdn_image", "") or card_data.get("cdn_image_url", "")
        if cdn_url and cdn_url != card.cdn_image_url:
            try:
                req = urllib.request.Request(cdn_url, headers={"User-Agent": "SuperTCG-Scanner/1.0"})
                with urllib.request.urlopen(req, timeout=15) as response:
                    img_data = response.read()
                    if img_data:
                        write_vals["image_base64"] = base64.b64encode(img_data).decode("ascii")
                        write_vals["cdn_image_url"] = cdn_url
            except Exception as img_err:
                _logger.warning("Failed to download updated image from %s: %s", cdn_url, img_err)

        # Recalculate pricing if relevant fields changed
        pricing_fields = {"price_low", "price_market", "condition", "card_category", "language", "purchase_basis"}
        if any(f in write_vals for f in pricing_fields):
            try:
                config = batch.env["supertcg.pricing.config"].get_config(batch.company_id)
                if config:
                    purchase_basis = write_vals.get("purchase_basis") or card.purchase_basis or card.price_low or 0.0
                    condition = write_vals.get("condition") or card.condition or "ex"
                    category = write_vals.get("card_category") or card.card_category or "other"
                    language = write_vals.get("language") or card.language or "en"

                    cash_pct = config.get_purchase_pct(condition)
                    credit_pct = config.get_credit_purchase_pct(condition)
                    increment = float(config.round_to)

                    purchase = round((purchase_basis * cash_pct / 100.0) / increment) * increment
                    purchase = max(purchase, config.purchase_min_price)

                    credit = round((purchase_basis * credit_pct / 100.0) / increment) * increment
                    credit = max(credit, config.purchase_min_price)

                    market = write_vals.get("price_market") or card.price_market or 0.0
                    market_based = round((market * config.sales_markup_pct / 100.0) / increment) * increment
                    market_based = max(market_based, config.sales_min_price)

                    lang = str(language).lower()
                    floor = config.get_sales_floor(category, False, condition, lang)
                    sales = max(market_based, floor)

                    write_vals["purchase_price"] = purchase
                    write_vals["credit_purchase_price"] = credit
                    write_vals["sales_price"] = sales
            except Exception as price_err:
                _logger.warning("Failed to recalculate pricing for updated card %s: %s", card.card_name, price_err)

        if write_vals:
            card.write(write_vals)
            return True
        return False

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "views": [[False, "form"]],
            "res_id": self.id,
            "target": "current",
        }

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'views': [[False, 'form']],
            'res_id': self.id,
            'target': 'current',
        }

    # ─── Image Fetching ───
    def action_fetch_images_from_cdn(self):
        """Download card images from CDN URLs for all cards missing image_base64."""
        self.ensure_one()
        self.log("Starting CDN image fetch", level='info', stage='image_fetch')

        fetched = 0
        errors = 0

        for card in self.card_line_ids:
            if card.image_base64:
                continue  # already has image

            cdn_url = card.cdn_image_url
            if not cdn_url:
                continue

            try:
                req = urllib.request.Request(cdn_url, headers={'User-Agent': 'SuperTCG-Scanner/1.0'})
                with urllib.request.urlopen(req, timeout=15) as response:
                    data = response.read()
                    if data:
                        b64 = base64.b64encode(data).decode('ascii')
                        card.image_base64 = b64
                        fetched += 1
            except Exception as e:
                _logger.warning("Failed to fetch image for card %s from %s: %s", card.card_name, cdn_url, str(e))
                errors += 1

        self.log("CDN image fetch complete — %s fetched, %s errors" % (fetched, errors), level='success', stage='image_fetch')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Images Fetched'),
                'message': _('%s images downloaded, %s errors') % (fetched, errors),
                'type': 'success',
                'sticky': False,
            }
        }

    # ─── Label Printing via Pi API ───
    def action_print_labels(self):
        """Send label data to the Pi for direct printing.
        
        The Pi generates ZPL and prints directly to the connected Zebra printer.
        Odoo no longer uses IoT — the Pi handles all printing.
        """
        self.ensure_one()

        if self.state != 'processed':
            self.log("Label print attempted before inventory (state=%s)" % self.state, level='warning', stage='print_start')
            raise UserError(_("Please add this batch to inventory before printing labels."))

        self.log("Starting label print job via Pi API", level='info', stage='print_start')

        # Get FINAL included cards after user edits/removals
        included_cards = self.card_line_ids.filtered(lambda c: c.is_included)
        if not included_cards:
            self.log("No included cards to print", level='warning', stage='print_start')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Cards'),
                    'message': _('No included cards to print.'),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        self.log("Found %s included cards" % len(included_cards), level='info', stage='print_start')

        # Get Pi URL from scanner device
        device = self.scanner_device_id
        if not device or not device.pi_url:
            self.log("No Pi URL configured for this batch", level='error', stage='printer_lookup')
            raise UserError(_("No Pi URL configured. Please set the Pi URL in Scanner → Devices."))

        # Build print labels API URL
        print_url = device.pi_url.replace('/api/batches', '/api/print-labels')
        api_key = device.api_key

        if not api_key:
            raise UserError(_("No API key configured for scanner device '%s'.") % device.name)

        # Build label payload — send FINAL data after user edits
        labels = []
        for card in included_cards:
            labels.append({
                'card_name': card.card_name or card.clean_name or 'Unknown',
                'remark': card.remark or card.condition or '',
                'set_code': card.set_code or '',
                'card_number': card.card_number or '',
                'printing': card.printing or 'Normal',
                'sales_price': float(card.sales_price or 0),
                'unique_barcode': card.unique_barcode or card.external_product_id or str(card.id),
            })

        payload = {'labels': labels}

        self.log("Sending %s labels to Pi at %s" % (len(labels), print_url), level='info', stage='iot_send')

        # Send to Pi
        try:
            req = urllib.request.Request(
                print_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'X-API-Key': api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))

            if result.get('ok'):
                self.log("Labels printed successfully via Pi: %s" % result.get('message', 'OK'), level='success', stage='iot_send')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Labels Printed'),
                        'message': _('%s labels sent to Pi printer.') % len(labels),
                        'type': 'success',
                        'sticky': False,
                    },
                }
            else:
                error_msg = result.get('error', 'Unknown Pi error')
                self.log("Pi print failed: %s" % error_msg, level='error', stage='iot_send')
                raise UserError(_("Pi print failed: %s") % error_msg)

        except urllib.error.HTTPError as e:
            self.log("Pi HTTP error %s: %s" % (e.code, e.reason), level='error', stage='iot_send')
            raise UserError(_("Pi printer error (HTTP %s): %s") % (e.code, e.reason))
        except urllib.error.URLError as e:
            self.log("Cannot connect to Pi: %s" % e.reason, level='error', stage='iot_send')
            raise UserError(_("Cannot connect to Pi printer at %s. Is it online?") % print_url)
        except Exception as e:
            self.log("Failed to print via Pi: %s" % str(e), level='error', stage='iot_send')
            raise UserError(_("Failed to print labels: %s") % str(e))

    # ─── ZPL Generation ───
    def _generate_batch_zpl(self, cards):
        """Generate combined ZPL for all cards in the batch."""
        zpl_parts = []
        for card in cards:
            card_zpl = self._generate_card_zpl(card)
            if card_zpl:
                zpl_parts.append(card_zpl)
        return '\n'.join(zpl_parts) if zpl_parts else False

    def _generate_card_zpl(self, card):
        """Generate ZPL for a single card label (1.5\" x 0.5\" @ 203dpi).

        Based on the Pi's working ZPL code. Layout:
          Row 1: Name (left), Condition (center), Price (right — biggest)
          Row 2: Set+Number (left), Printing (center)
          Row 3: Barcode (thick ^BY4 bars)
        """
        def _safe(text, max_len=30):
            t = str(text or '').replace("^", " ").replace("~", " ")
            t = t.encode("ascii", "ignore").decode("ascii")
            return t[:max_len]

        raw_name = _safe(card.card_name, 30)
        price = card.sales_price or 0.0
        # Label shows SuperTCG Sales price (not market price)
        price_str = f"EUR{price:,.2f}".replace(",", ".") if price else "EUR0.00"

        # ── Label Dimensions ──────────────────────────────────────────────
        LABEL_W = 304
        LABEL_H = 101

        # ── Fonts (match Pi working code) ─────────────────────────────────
        PRICE_FONT_H = 34
        PRICE_FONT_W = 20
        NAME_FONT_H = 22
        NAME_FONT_W = 12
        SMALL_FONT_H = 18
        SMALL_FONT_W = 14

        # ── Positions ─────────────────────────────────────────────────────
        LEFT_MARGIN = 22          # more right to avoid left-edge clipping
        COND_X = 158              # center column for condition / printing
        RIGHT_MARGIN = 2

        # Right-align price
        price_width = len(price_str) * PRICE_FONT_W
        price_x = LABEL_W - RIGHT_MARGIN - price_width
        if price_x < 170:
            price_x = 170

        # Truncate name to fit before price
        max_name_width = price_x - LEFT_MARGIN - 8
        max_name_chars = max_name_width // NAME_FONT_W
        if max_name_chars < 6:
            max_name_chars = 6
        name = raw_name[:max_name_chars] if len(raw_name) > max_name_chars else raw_name

        cond = _safe(card.remark, 6)
        set_num = f"{_safe(card.set_code, 6)}  {_safe(card.card_number, 8)}".strip() if (card.set_code or card.card_number) else ""
        print_type = _safe(card.printing, 10)
        barcode_data = str(card.unique_barcode) if card.unique_barcode else str(card.external_product_id) if card.external_product_id else "0"

        # ── ZPL Output (Pi layout: shifted right + down for centering) ────
        # y positions pushed down to vertically center content on 1.5\"x0.5\" label
        zpl = f"""^XA
^PW{LABEL_W}
^LL{LABEL_H}
^LH0,0
^CI28

; Row 1 — Name (left), Condition (center), Price (right, biggest)
^FO{LEFT_MARGIN},12^A0N,{NAME_FONT_H},{NAME_FONT_W}^FD{name}^FS
^FO{COND_X},14^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{cond}^FS
^FO{price_x},12^A0N,{PRICE_FONT_H},{PRICE_FONT_W}^FD{price_str}^FS

; Row 2 — Set+Number (left), Printing (center)
^FO{LEFT_MARGIN},46^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{set_num}^FS
^FO{COND_X},46^A0N,{SMALL_FONT_H},{SMALL_FONT_W}^FD{print_type}^FS

; Barcode (wider ^BY4 for density matching SortSwift)
^FO{LEFT_MARGIN},68^BY4^BCN,32,N,N,N,A^FD{barcode_data}^FS

^XZ"""
        return zpl

    # ─── Product Helpers ───
    def _get_or_create_product(self, card, product_cache):
        """Find or create a product.product for a card."""
        self.ensure_one()

        if not card.external_product_id:
            _logger.warning("Card %s has no external_product_id, skipping product creation.", card.card_name)
            return False

        # Use unique_barcode (based on card parameters) for product identification
        barcode = card.unique_barcode or card.external_product_id

        # Check cache
        if barcode in product_cache:
            product = product_cache[barcode]
            self._update_product_image(product, card)
            return product

        # Search existing
        product = self.env['product.product'].search([
            ('default_code', '=', barcode),
        ], limit=1)

        if product:
            self._update_product_image(product, card)
            product_cache[barcode] = product
            return product

        # Create new product
        if self.product_category_id:
            category = self.product_category_id
        else:
            category = self._get_or_create_category(card.game_name)

        # Build descriptive product name
        name_parts = [card.card_name or card.clean_name or 'Unknown Card']
        if card.card_number:
            name_parts.append(card.card_number)
        if card.condition and card.condition != 'ex':
            name_parts.append(card.condition.upper())
        if card.printing and card.printing != 'Normal':
            name_parts.append(card.printing)
        product_name = ' - '.join(name_parts)

        product_vals = {
            'name': product_name,
            'default_code': card.external_product_id,
            'barcode': barcode,
            'description': self._build_description(card),
            'standard_price': card.purchase_price or card.price_market or 0.0,
            'list_price': card.sales_price or card.price_market or 0.0,
            'categ_id': category.id,
            'type': 'consu',
            'is_storable': True,
            'sale_ok': True,
            'purchase_ok': True,
            'available_in_pos': True,
            'is_published': True,
            'website_published': True,
            'company_id': self.company_id.id,
        }

        # Website categories
        if self.website_category_ids:
            product_vals['public_categ_ids'] = [(6, 0, self.website_category_ids.ids)]

        # Apply 2nd-hand margin taxes if available in this company
        # Sales tax (Margeverkoop)
        sale_tax = self.env['account.tax'].sudo().search([
            ('name', '=', 'Margeverkoop'),
            ('type_tax_use', '=', 'sale'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if sale_tax:
            product_vals['taxes_id'] = [(6, 0, [sale_tax.id])]

        # Purchase tax (Margeinkoop)
        purchase_tax = self.env['account.tax'].sudo().search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if purchase_tax:
            product_vals['supplier_taxes_id'] = [(6, 0, [purchase_tax.id])]

        # Set image
        image = self._get_card_image(card)
        if image:
            product_vals['image_1920'] = image

        product = self.env['product.product'].create(product_vals)
        product_cache[barcode] = product
        return product

    def _get_or_create_category(self, game_name):
        """Find or create a product category by game name."""
        if not game_name:
            game_name = 'Trading Cards'
        category = self.env['product.category'].search([
            ('name', '=', game_name),
        ], limit=1)
        if not category:
            category = self.env['product.category'].create({
                'name': game_name,
            })
        return category

    def _build_description(self, card):
        """Build product description from card data."""
        parts = []
        if card.set_name:
            parts.append(card.set_name)
        if card.card_number:
            parts.append(card.card_number)
        if card.rarity:
            parts.append(card.rarity)
        if card.printing:
            parts.append(card.printing)
        if card.edition:
            parts.append(card.edition)
        if card.language:
            parts.append(card.language)
        return ' — '.join(parts) if parts else ''

    def _get_card_image(self, card):
        """Get image data for a card, preferring scan image, then base64, then CDN."""
        # 1. Prefer real scan image from the Pi if available
        if card.cdn_scan_image_url:
            try:
                req = urllib.request.Request(
                    card.cdn_scan_image_url,
                    headers={'User-Agent': 'SuperTCG-Scanner/1.0'}
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    return base64.b64encode(response.read())
            except Exception as e:
                _logger.warning("Failed to download scan image from %s: %s", card.cdn_scan_image_url, str(e))

        # 2. Fallback to stored base64 (usually official SortSwift image)
        if card.image_base64:
            return card.image_base64

        # 3. Last resort: download from official SortSwift CDN
        if card.cdn_image_url:
            try:
                req = urllib.request.Request(
                    card.cdn_image_url,
                    headers={'User-Agent': 'SuperTCG-Scanner/1.0'}
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    return base64.b64encode(response.read())
            except Exception as e:
                _logger.warning("Failed to download image from %s: %s", card.cdn_image_url, str(e))

        return False

    def _update_product_image(self, product, card):
        """Always update product image with the real scan image."""
        image = self._get_card_image(card)
        if image:
            product.write({'image_1920': image})
