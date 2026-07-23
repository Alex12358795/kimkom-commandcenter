import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class SuperTCGPricingConfig(models.Model):
    _name = 'supertcg.pricing.config'
    _description = 'SuperTCG Scanner Pricing Configuration'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Store',
        required=True,
        default=lambda self: self.env.company,
    )

    # ─── Purchase Pricing ───
    purchase_nm_ex_pct = fields.Float(
        string='NM / EX Purchase %',
        default=70.0,
        help='Percentage of price_low offered for Near Mint and Excellent cards.',
    )
    purchase_other_pct = fields.Float(
        string='Other Condition Purchase %',
        default=60.0,
        help='Percentage of price_low offered for VG, G, LP, MP, HP, DMG cards.',
    )
    purchase_pl_po_pct = fields.Float(
        string='PL / PO Purchase %',
        default=60.0,
        help='Percentage of price_low offered for Played and Poor cards. Set to 0 to exclude.',
    )
    purchase_credit_premium = fields.Float(
        string='Store Credit Premium (pp)',
        default=10.0,
        help='Additional percentage points for store credit vs cash (e.g., 10 = 80% vs 70%).',
    )
    purchase_min_price = fields.Float(
        string='Minimum Purchase Price',
        default=0.05,
        help='Lowest purchase price we will ever offer.',
    )

    # ─── Sales Pricing ───
    sales_markup_pct = fields.Float(
        string='Sales Markup %',
        default=120.0,
        help='Percentage of price_market used as market-based sales price (e.g., 120%% = €1.20 on €1.00).',
    )
    sales_min_price = fields.Float(
        string='Minimum Sales Price',
        default=0.10,
        help='Lowest sales price we will ever list.',
    )

    # ─── Category Floor Prices (Sales) ───
    floor_common_uncommon = fields.Float(
        string='Common / Uncommon Floor',
        default=0.25,
        help='Minimum sales price for non-WOTC commons and uncommons.',
    )
    floor_holo = fields.Float(
        string='Holo Floor',
        default=1.00,
        help='Minimum sales price for holo cards.',
    )
    floor_reverse_holo = fields.Float(
        string='Reverse Holo Floor',
        default=1.00,
        help='Minimum sales price for reverse holo cards.',
    )
    floor_ex_en = fields.Float(
        string='EX Floor (English)',
        default=2.50,
        help='Minimum sales price for English EX cards.',
    )
    floor_ex_jp = fields.Float(
        string='EX Floor (Japanese)',
        default=2.00,
        help='Minimum sales price for Japanese EX cards.',
    )
    floor_v_en = fields.Float(
        string='V Floor (English)',
        default=2.50,
        help='Minimum sales price for English V cards.',
    )
    floor_v_jp = fields.Float(
        string='V Floor (Japanese)',
        default=2.00,
        help='Minimum sales price for Japanese V cards.',
    )
    floor_vmax = fields.Float(
        string='VMAX Floor',
        default=3.00,
        help='Minimum sales price for VMAX cards.',
    )
    floor_full_art = fields.Float(
        string='Full Art Floor',
        default=4.00,
        help='Minimum sales price for Full Art cards.',
    )
    floor_alternate_art = fields.Float(
        string='Alternate Art Floor',
        default=4.00,
        help='Minimum sales price for Alternate Art cards.',
    )
    floor_wotc_common_nm = fields.Float(
        string='WOTC Common NM Floor',
        default=3.00,
        help='Minimum sales price for Near Mint WOTC commons.',
    )
    floor_wotc_common_below_nm = fields.Float(
        string='WOTC Common Below-NM Floor',
        default=2.00,
        help='Minimum sales price for WOTC commons below Near Mint.',
    )

    # ─── Slab Pricing (Future Use) ───
    slab_high_grade_pct = fields.Float(
        string='High-Grade Slab Purchase %',
        default=70.0,
        help='Purchase % for high-grade slabs (PSA 10, BGS 10, CGC 10).',
    )
    slab_low_grade_pct = fields.Float(
        string='Low-Grade Slab Purchase %',
        default=60.0,
        help='Purchase % for lower-grade slabs (PSA 6-8, unknown graders).',
    )
    slab_tier1_pct = fields.Float(
        string='Slab Tier 1 (€250+ Cash) %',
        default=70.0,
        help='Tier 1: immediate cash/store credit for slabs €250+.',
    )
    slab_tier2_pct = fields.Float(
        string='Slab Tier 2 (2wk Payout) %',
        default=75.0,
        help='Tier 2: payout after 2 weeks.',
    )
    slab_tier3_pct = fields.Float(
        string='Slab Tier 3 (1mo Wire) %',
        default=80.0,
        help='Tier 3: wire transfer after 1 month.',
    )

    # ─── WOTC & New Set ───
    wotc_set_codes = fields.Char(
        string='WOTC Set Codes',
        default='BS,JU,FO,TR,B2,GH,GC,N1,N2,N3,N4,EXP,AQP,SK',
        help='Comma-separated list of WOTC-era set codes.',
    )
    new_set_warning_days = fields.Integer(
        string='New Set Warning (Days)',
        default=21,
        help='Show warning for cards from sets released within this many days.',
    )

    # ─── Rounding ───
    round_to = fields.Selection(
        selection=[
            ('0.05', '€0.05'),
            ('0.10', '€0.10'),
            ('0.25', '€0.25'),
            ('0.50', '€0.50'),
            ('1.00', '€1.00'),
        ],
        string='Round Prices To',
        default='0.05',
        help='Round calculated prices to the nearest increment.',
    )

    _sql_constraints = [
        ('company_unique', 'UNIQUE(company_id)', 'Only one pricing config allowed per company.'),
    ]

    @api.depends('company_id')
    def _compute_name(self):
        for config in self:
            config.name = config.company_id.name or 'Pricing Config'

    @api.model
    def get_config(self, company=None):
        """Get or create pricing config for a company."""
        company = company or self.env.company
        config = self.search([('company_id', '=', company.id)], limit=1)
        if not config:
            config = self.create({'company_id': company.id})
        return config

    def _round_price(self, price):
        """Round a price to the configured increment."""
        self.ensure_one()
        increment = float(self.round_to)
        return round(price / increment) * increment

    def get_purchase_pct(self, condition):
        """Get purchase percentage for a given condition code."""
        self.ensure_one()
        if condition in ('nm', 'ex'):
            return self.purchase_nm_ex_pct
        if condition in ('pl', 'po'):
            return self.purchase_pl_po_pct
        return self.purchase_other_pct

    def get_credit_purchase_pct(self, condition):
        """Get store credit purchase percentage for a given condition code."""
        self.ensure_one()
        return self.get_purchase_pct(condition) + self.purchase_credit_premium

    def get_sales_floor(self, category, is_wotc=False, condition='ex', language='en'):
        """Get sales floor price for a card category."""
        self.ensure_one()
        lang = (language or '').lower()
        is_jp = lang in ('ja', 'jp', 'japanese', 'japans')

        if category in ('common', 'uncommon') and is_wotc:
            if condition == 'nm':
                return self.floor_wotc_common_nm
            return self.floor_wotc_common_below_nm

        floors = {
            'common': self.floor_common_uncommon,
            'uncommon': self.floor_common_uncommon,
            'holo': self.floor_holo,
            'reverse_holo': self.floor_reverse_holo,
            'ex': self.floor_ex_jp if is_jp else self.floor_ex_en,
            'v': self.floor_v_jp if is_jp else self.floor_v_en,
            'vmax': self.floor_vmax,
            'full_art': self.floor_full_art,
            'alternate_art': self.floor_alternate_art,
        }
        return floors.get(category, 0.0)

    def apply_formula(self, card):
        """Apply SOP pricing formula to a batch card record.

        Returns dict with purchase_price, credit_purchase_price, sales_price.
        """
        self.ensure_one()
        condition = card.condition or 'ex'
        category = card.card_category or 'other'
        is_wotc = card.is_wotc
        language = card.language or 'en'

        # ─── Purchase Price ───
        basis = card.purchase_basis or card.price_low or card.price_market or 0.0
        cash_pct = self.get_purchase_pct(condition)
        credit_pct = self.get_credit_purchase_pct(condition)

        purchase = self._round_price(basis * cash_pct / 100.0)
        purchase = max(purchase, self.purchase_min_price)

        credit_purchase = self._round_price(basis * credit_pct / 100.0)
        credit_purchase = max(credit_purchase, self.purchase_min_price)

        # ─── Safety Cap: Purchase price can never exceed market price ───
        market = card.price_market or 0.0
        if purchase > market and market > 0:
            _logger.warning(
                "Pricing safety cap triggered for %s: purchase €%.2f > market €%.2f, capping at market",
                card.card_name, purchase, market
            )
            purchase = market
        if credit_purchase > market and market > 0:
            credit_purchase = market

        # ─── Sales Price ───
        market_based = self._round_price(market * self.sales_markup_pct / 100.0)
        market_based = max(market_based, self.sales_min_price)

        floor = self.get_sales_floor(category, is_wotc, condition, language)
        sales = max(market_based, floor)

        return {
            'purchase_price': purchase,
            'credit_purchase_price': credit_purchase,
            'sales_price': sales,
        }
