import hashlib

from odoo import api, fields, models, _
from odoo.tools.barcode import get_barcode_check_digit


CONDITION_SELECTION = [
    ('nm', 'Near Mint'),
    ('ex', 'Excellent'),
    ('vg', 'Very Good'),
    ('g', 'Good'),
    ('lp', 'Lightly Played'),
    ('mp', 'Moderately Played'),
    ('hp', 'Heavily Played'),
    ('pl', 'Played'),
    ('po', 'Poor'),
    ('dmg', 'Damaged'),
]

CARD_CATEGORY_SELECTION = [
    ('common', 'Common'),
    ('uncommon', 'Uncommon'),
    ('holo', 'Holo'),
    ('reverse_holo', 'Reverse Holo'),
    ('ex', 'EX'),
    ('v', 'V'),
    ('vmax', 'VMAX'),
    ('full_art', 'Full Art'),
    ('alternate_art', 'Alternate Art'),
    ('secret_rare', 'Secret Rare'),
    ('other', 'Other'),
]


# HARDCODE-ISSUE-5: _rec_name defaults to 'name' but this model uses 'card_name'.
class SuperTCGBatchCard(models.Model):
    _name = 'supertcg.batch.card'
    _description = 'SuperTCG Scanner Batch Card'
    _order = 'sequence, id'
    _rec_name = 'card_name'

    # ─── Parent ───
    batch_id = fields.Many2one(
        'supertcg.batch',
        string='Batch',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ─── Scan Metadata ───
    sequence = fields.Integer(
        string='Seq',
        default=0,
        help='Scan order within the batch',
    )
    scanner_alias = fields.Char(
        string='Scanner',
        help='Human-readable scanner name',
    )
    timestamp = fields.Char(
        string='Scanned At',
        help='Individual card scan timestamp (raw Unix timestamp from the Pi)',
    )

    # ─── Card Identification ───
    game_name = fields.Char(
        string='Game',
        help='Pokemon, Magic, YuGiOh, etc.',
    )
    card_name = fields.Char(
        string='Card Name',
        required=True,
    )
    clean_name = fields.Char(
        string='Clean Name',
        help='Normalized card name',
    )
    card_number = fields.Char(
        string='Card Number',
        help='Collector number (e.g., 152/181)',
    )
    set_code = fields.Char(
        string='Set Code',
        help='Short set code (e.g., SM9)',
    )
    set_name = fields.Char(
        string='Set Name',
    )
    external_product_id = fields.Char(
        string='External Product ID',
        help='Unique product ID from SortSwift / TCGplayer',
        index=True,
    )
    unique_barcode = fields.Char(
        string='Barcode',
        compute='_compute_unique_barcode',
        store=True,
        help='Unique EAN-13 barcode based on card parameters (product, condition, printing, language, foil).',
    )
    handle = fields.Char(
        string='Handle',
        help='URL-safe handle',
    )
    group_id = fields.Char(
        string='Group ID',
    )
    category_id = fields.Char(
        string='Category ID',
    )

    # ─── Card Attributes ───
    rarity = fields.Char(
        string='Rarity',
    )
    published_year = fields.Integer(
        string='Year',
    )
    printing = fields.Char(
        string='Printing',
        help='Normal, Foil, Holofoil, Reverse Holo, etc.',
    )
    edition = fields.Char(
        string='Edition',
        help='Unlimited, 1st Edition, etc.',
    )
    language = fields.Char(
        string='Language',
    )
    foil = fields.Boolean(
        string='Foil',
        default=False,
    )
    is_reverse_holo = fields.Boolean(
        string='Reverse Holo',
        default=False,
    )

    # ─── Condition & Quality ───
    condition = fields.Selection(
        CONDITION_SELECTION,
        string='Condition',
        default='ex',
        help='Card condition used for pricing calculations.',
    )
    remark = fields.Char(
        string='Raw Condition',
        help='Raw condition string from the Pi payload (mapped to condition field).',
    )
    status = fields.Char(
        string='Status',
        help='ok or error',
    )
    is_error_card = fields.Boolean(
        string='Error Card',
        default=False,
    )
    confidence = fields.Float(
        string='Confidence',
        help='AI recognition confidence (0.0–1.0)',
        digits=(3, 2),
    )
    possible_mismatch = fields.Boolean(
        string='Mismatch',
        default=False,
        help='Flag if AI is unsure about the match',
    )
    mismatch_reason = fields.Char(
        string='Mismatch Reason',
    )

    # ─── Extended Card Attributes (from Pi ext_* fields) ───
    ext_card_type = fields.Char(
        string='Card Type',
        help='e.g., Colorless, Fire, Water',
    )
    ext_hp = fields.Char(
        string='HP',
        help='Hit points',
    )
    ext_stage = fields.Char(
        string='Stage',
        help='e.g., Basic, Stage 1, Stage 2',
    )
    ext_cardtext = fields.Text(
        string='Card Text',
        help='Full card text / abilities',
    )
    ext_attack_1 = fields.Char(
        string='Attack 1',
    )
    ext_attack_2 = fields.Char(
        string='Attack 2',
    )
    ext_weakness = fields.Char(
        string='Weakness',
    )
    ext_resistance = fields.Char(
        string='Resistance',
    )
    ext_retreatcost = fields.Char(
        string='Retreat Cost',
    )

    # ─── Card Category (Auto-detected, editable) ───
    card_category = fields.Selection(
        CARD_CATEGORY_SELECTION,
        string='Card Category',
        default='other',
        help='Auto-detected from rarity/printing/card name. Staff can override.',
    )
    is_wotc = fields.Boolean(
        string='WOTC',
        compute='_compute_is_wotc',
        store=True,
        help='True if this card is from a WOTC-era set.',
    )
    is_new_set = fields.Boolean(
        string='New Set',
        compute='_compute_is_new_set',
        store=True,
        help='True if this card is from a recently released set.',
    )

    # ─── Pricing ───
    price_low = fields.Float(
        string='Price Low',
        digits=(16, 2),
    )
    price_mid = fields.Float(
        string='Price Mid',
        digits=(16, 2),
    )
    price_high = fields.Float(
        string='Price High',
        digits=(16, 2),
    )
    price_market = fields.Float(
        string='Price Market',
        digits=(16, 2),
    )
    price_direct_low = fields.Float(
        string='Price Direct Low',
        digits=(16, 2),
    )
    purchase_basis = fields.Float(
        string='Purchase Basis',
        digits=(16, 2),
        help='The price_low value used as basis for purchase calculations.',
    )

    # ─── SuperTCG Calculated Pricing ───
    purchase_price = fields.Float(
        string='SuperTCG Purchase (Cash)',
        digits=(16, 2),
        compute='_compute_pricing',
        store=True,
        help='Cash price we offer to the customer.',
    )
    credit_purchase_price = fields.Float(
        string='SuperTCG Purchase (Store Credit)',
        digits=(16, 2),
        compute='_compute_pricing',
        store=True,
        help='Store credit price we offer to the customer.',
    )
    sales_price = fields.Float(
        string='SuperTCG Sales',
        digits=(16, 2),
        compute='_compute_pricing',
        store=True,
        help='Price we will list the card for after inventory intake.',
    )
    purchase_breakdown = fields.Char(
        string='Purchase Formula',
        compute='_compute_pricing',
        store=True,
        help='Shows how cash and store credit prices are calculated.',
    )
    sales_breakdown = fields.Char(
        string='Sales Formula',
        compute='_compute_pricing',
        store=True,
        help='Shows how the sales price is calculated.',
    )

    # ─── Images ───
    cdn_image_url = fields.Char(
        string='CDN Image URL',
        help='URL to official card image',
    )
    cdn_scan_image_url = fields.Char(
        string='CDN Scan URL',
        help='URL to the actual scanned image',
    )
    image_base64 = fields.Binary(
        string='Card Image',
        help='Base64-encoded official card image',
    )

    # ─── Extended Data ───
    ext_data = fields.Json(
        string='Extended Data',
        help='All ext_* fields from the payload (game-specific)',
    )

    # ─── Processing ───
    is_included = fields.Boolean(
        string='Include',
        default=True,
        help='Toggle to include/exclude this card from processing',
    )
    product_product_id = fields.Many2one(
        'product.product',
        string='Product',
        help='Linked Odoo product after inventory processing',
        readonly=True,
    )
    notes = fields.Text(
        string='Notes',
        help='Internal notes about this card',
    )

    # ─── Multi-Company (related) ───
    company_id = fields.Many2one(
        'res.company',
        related='batch_id.company_id',
        store=True,
        readonly=True,
    )

    # ─── Compute Methods ───
    @api.depends('set_code', 'batch_id.company_id')
    def _compute_is_wotc(self):
        for card in self:
            if not card.set_code:
                card.is_wotc = False
                continue
            company = card.company_id or card.batch_id.company_id or self.env.company
            config = self.env['supertcg.pricing.config'].get_config(company)
            wotc_codes = [c.strip().upper() for c in (config.wotc_set_codes or '').split(',') if c.strip()]
            card.is_wotc = card.set_code.strip().upper() in wotc_codes

    @api.depends('published_year')
    def _compute_is_new_set(self):
        from datetime import datetime
        current_year = datetime.now().year
        for card in self:
            card.is_new_set = bool(card.published_year and card.published_year >= current_year)

    @api.depends(
        'purchase_basis', 'price_market', 'condition', 'card_category',
        'is_wotc', 'language', 'batch_id.company_id'
    )
    def _compute_pricing(self):
        for card in self:
            if not card.purchase_basis and not card.price_market:
                card.purchase_price = 0.0
                card.credit_purchase_price = 0.0
                card.sales_price = 0.0
                card.purchase_breakdown = ""
                card.sales_breakdown = ""
                continue

            company = card.company_id or card.batch_id.company_id or self.env.company
            config = self.env['supertcg.pricing.config'].get_config(company)
            prices = config.apply_formula(card)
            card.purchase_price = prices['purchase_price']
            card.credit_purchase_price = prices['credit_purchase_price']
            card.sales_price = prices['sales_price']

            # Build separate breakdown strings with actual numbers
            condition = card.condition or 'ex'
            category = card.card_category or 'other'
            cash_pct = config.get_purchase_pct(condition)
            credit_pct = config.get_credit_purchase_pct(condition)
            floor = config.get_sales_floor(category, card.is_wotc, condition, card.language or 'en')
            basis = card.purchase_basis or card.price_low or card.price_market or 0.0
            market = card.price_market or 0.0

            # Purchase breakdown: Cash + Store Credit
            raw_cash = basis * cash_pct / 100.0
            raw_credit = basis * credit_pct / 100.0
            cash_capped = raw_cash > market and market > 0
            credit_capped = raw_credit > market and market > 0
            
            cash_str = f"Cash: €{basis:.2f} (low) × {cash_pct:g}%"
            if cash_capped:
                cash_str += f" = €{raw_cash:.2f} → capped at market €{card.purchase_price:.2f}"
            else:
                cash_str += f" = €{card.purchase_price:.2f}"
            
            credit_str = f"Store Credit: €{basis:.2f} (low) × {credit_pct:g}%"
            if credit_capped:
                credit_str += f" = €{raw_credit:.2f} → capped at market €{card.credit_purchase_price:.2f}"
            else:
                credit_str += f" = €{card.credit_purchase_price:.2f}"
            
            card.purchase_breakdown = f"{cash_str} | {credit_str}"
            
            # Sales breakdown
            market_calc = market * config.sales_markup_pct / 100.0
            if floor > 0:
                card.sales_breakdown = (
                    f"max(€{market:.2f} (market) × {config.sales_markup_pct:g}% = €{market_calc:.2f}, "
                    f"floor €{floor:.2f}) = €{card.sales_price:.2f}"
                )
            else:
                card.sales_breakdown = (
                    f"€{market:.2f} (market) × {config.sales_markup_pct:g}% = €{card.sales_price:.2f}"
                )

    @api.depends('external_product_id', 'card_number', 'set_code', 'condition', 'printing', 'language', 'foil', 'is_reverse_holo')
    def _compute_unique_barcode(self):
        """Generate a unique EAN-13 barcode based on card parameters.
        
        Cards with the same parameters get the same barcode, so inventory
        quantities aggregate instead of creating separate product lines.
        """
        # Group cards by batch to detect collisions
        batch_ids = set(self.mapped('batch_id.id'))
        
        for batch_id in batch_ids:
            batch_cards = self.filtered(lambda c: c.batch_id.id == batch_id)
            # Sort by ID for stable ordering
            batch_cards = batch_cards.sorted(key=lambda c: c.id)
            used_barcodes = {}  # barcode -> first card with this barcode
            collision_counters = {}  # base_key -> counter
            
            for card in batch_cards:
                if not card.external_product_id:
                    card.unique_barcode = False
                    continue
                
                # Build a unique key from distinguishing parameters
                key_parts = [
                    str(card.external_product_id),
                    str(card.card_number or ''),
                    str(card.set_code or ''),
                    str(card.condition or 'ex'),
                    str(card.printing or 'Normal'),
                    str(card.language or 'EN'),
                    '1' if card.foil else '0',
                    '1' if card.is_reverse_holo else '0',
                ]
                base_key = '|'.join(key_parts)
                
                # Check for collisions: same base key but different card (different price)
                collision_key = base_key
                if base_key in used_barcodes:
                    existing = used_barcodes[base_key]
                    # If prices differ significantly, it's a different card -> need unique barcode
                    if abs(card.price_market - existing.price_market) > 0.01:
                        # Use collision counter to generate unique suffix
                        collision_counters[base_key] = collision_counters.get(base_key, 1) + 1
                        collision_key = f"{base_key}#{collision_counters[base_key]}"
                
                # Hash to a numeric identifier (max 10 digits for EAN-13)
                hash_int = int(hashlib.md5(collision_key.encode()).hexdigest(), 16)
                identifier = str(hash_int % 10_000_000_000).zfill(10)
                
                # Generate EAN-13 with prefix 20 (internal use)
                base = '20' + identifier
                checksum = get_barcode_check_digit(base + '0')
                barcode = f"{base}{checksum}"
                
                # Store mapping
                if base_key not in used_barcodes:
                    used_barcodes[base_key] = card
                
                card.unique_barcode = barcode

    # ─── Helpers ───
    @api.model
    def map_condition(self, remark):
        """Map raw Pi condition string to internal condition code."""
        if not remark:
            return 'ex'
        remark_lower = str(remark).strip().lower()
        mapping = {
            'near mint': 'nm',
            'nm': 'nm',
            'excellent': 'ex',
            'ex': 'ex',
            'very good': 'vg',
            'vg': 'vg',
            'good': 'g',
            'g': 'g',
            'lightly played': 'lp',
            'lp': 'lp',
            'moderately played': 'mp',
            'mp': 'mp',
            'heavily played': 'hp',
            'hp': 'hp',
            'played': 'pl',
            'pl': 'pl',
            'poor': 'po',
            'po': 'po',
            'damaged': 'dmg',
            'dmg': 'dmg',
        }
        return mapping.get(remark_lower, 'ex')

    @api.model
    def detect_card_category(self, card_data):
        """Auto-detect card category from Pi payload fields."""
        rarity = str(card_data.get('rarity', '')).lower()
        printing = str(card_data.get('printing', '')).lower()
        name = str(card_data.get('card_name', '')).lower()
        is_reverse = str(card_data.get('is_reverse_holo', '')).lower() == 'true'
        is_foil = str(card_data.get('foil', '')).lower() == 'true'

        if is_reverse:
            return 'reverse_holo'
        if is_foil and 'holo' in printing:
            return 'holo'
        if 'common' in rarity and 'uncommon' not in rarity:
            return 'common'
        if 'uncommon' in rarity:
            return 'uncommon'
        if ' secret' in name or 'secret rare' in rarity:
            return 'secret_rare'
        if 'vmax' in rarity:
            return 'vmax'
        if ' vmax' in name or name.endswith('vmax'):
            return 'vmax'
        if ' v ' in name or name.endswith(' v'):
            return 'v'
        if ' ex' in name or name.endswith(' ex'):
            return 'ex'
        if 'full art' in name or 'full art' in rarity:
            return 'full_art'
        if 'alternate' in name or 'alternate' in rarity or ' alt ' in name:
            return 'alternate_art'

        return 'other'

    # ─── Actions ───
    def action_open_product(self):
        """Open the linked product in inventory."""
        self.ensure_one()
        if not self.product_product_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Product'),
                    'message': _('This card has not been added to inventory yet.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product'),
            'res_model': 'product.product',
            'res_id': self.product_product_id.id,
            'view_mode': 'form',
            'target': 'new',
        }
