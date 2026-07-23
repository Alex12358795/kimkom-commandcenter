from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestPricingConfig(TransactionCase):
    """Test the SOP-compliant pricing engine."""

    def setUp(self):
        super().setUp()
        # Create a test company to avoid unique constraint on pricing config
        self.test_company = self.env['res.company'].create({
            'name': 'Test Company',
        })
        self.config = self.env['supertcg.pricing.config'].create({
            'company_id': self.test_company.id,
            'purchase_nm_ex_pct': 70.0,
            'purchase_other_pct': 60.0,
            'purchase_pl_po_pct': 50.0,
            'purchase_credit_premium': 10.0,
            'purchase_min_price': 0.05,
            'sales_markup_pct': 120.0,
            'sales_min_price': 0.10,
            'round_to': '0.05',
            'floor_common_uncommon': 0.25,
            'floor_holo': 1.0,
            'floor_reverse_holo': 1.0,
            'floor_ex_en': 2.50,
            'floor_ex_jp': 2.0,
            'floor_v_en': 2.50,
            'floor_v_jp': 2.0,
            'floor_vmax': 3.0,
            'floor_full_art': 4.0,
            'floor_alternate_art': 4.0,
            'floor_wotc_common_nm': 3.0,
            'floor_wotc_common_below_nm': 2.0,
        })

    def test_purchase_nm_ex_percentage(self):
        """NM/EX cards get 70% of purchase basis."""
        pct = self.config.get_purchase_pct('nm')
        self.assertEqual(pct, 70.0)
        pct = self.config.get_purchase_pct('ex')
        self.assertEqual(pct, 70.0)

    def test_purchase_other_percentage(self):
        """Non-NM/EX cards get 60% of purchase basis."""
        for condition in ['vg', 'g', 'lp', 'mp', 'hp', 'dmg']:
            pct = self.config.get_purchase_pct(condition)
            self.assertEqual(pct, 60.0, f"Condition {condition} should be 60%")

    def test_purchase_pl_po_percentage(self):
        """PL/PO cards get configurable percentage (default 50%)."""
        self.assertEqual(self.config.get_purchase_pct('pl'), 50.0)
        self.assertEqual(self.config.get_purchase_pct('po'), 50.0)

    def test_credit_purchase_percentage(self):
        """Store credit adds premium to cash percentage."""
        cash = self.config.get_purchase_pct('nm')
        credit = self.config.get_credit_purchase_pct('nm')
        self.assertEqual(credit, cash + 10.0)

    def test_round_price(self):
        """Prices round to configured increment."""
        self.assertAlmostEqual(self.config._round_price(1.23), 1.25, places=2)
        self.assertAlmostEqual(self.config._round_price(1.21), 1.20, places=2)
        self.assertAlmostEqual(self.config._round_price(1.02), 1.00, places=2)

    def test_sales_floor_common(self):
        """Common cards have €0.25 floor."""
        floor = self.config.get_sales_floor('common', False, 'nm', 'en')
        self.assertEqual(floor, 0.25)

    def test_sales_floor_holo(self):
        """Holo cards have €1.00 floor."""
        floor = self.config.get_sales_floor('holo', False, 'nm', 'en')
        self.assertEqual(floor, 1.0)

    def test_sales_floor_ex_english(self):
        """English EX cards have €2.50 floor."""
        floor = self.config.get_sales_floor('ex', False, 'nm', 'en')
        self.assertEqual(floor, 2.50)

    def test_sales_floor_ex_japanese(self):
        """Japanese EX cards have €2.00 floor."""
        floor = self.config.get_sales_floor('ex', False, 'nm', 'ja')
        self.assertEqual(floor, 2.0)

    def test_sales_floor_full_art(self):
        """Full Art cards have €4.00 floor."""
        floor = self.config.get_sales_floor('full_art', False, 'nm', 'en')
        self.assertEqual(floor, 4.0)

    def test_sales_floor_wotc_common_nm(self):
        """WOTC commons in NM have €3.00 floor."""
        floor = self.config.get_sales_floor('common', True, 'nm', 'en')
        self.assertEqual(floor, 3.0)

    def test_sales_floor_wotc_common_ex(self):
        """WOTC commons below NM have €2.00 floor."""
        floor = self.config.get_sales_floor('common', True, 'ex', 'en')
        self.assertEqual(floor, 2.0)

    def test_apply_formula_purchase(self):
        """Test full pricing formula for purchase price."""
        # Create a mock card
        card = self.env['supertcg.batch.card'].new({
            'condition': 'nm',
            'card_category': 'common',
            'language': 'en',
            'purchase_basis': 10.0,
            'price_market': 12.0,
            'is_wotc': False,
        })
        prices = self.config.apply_formula(card)
        # 10.0 * 0.70 = 7.0, rounded to 0.05 = 7.00
        self.assertEqual(prices['purchase_price'], 7.0)

    def test_apply_formula_credit(self):
        """Test full pricing formula for credit purchase price."""
        card = self.env['supertcg.batch.card'].new({
            'condition': 'nm',
            'card_category': 'common',
            'language': 'en',
            'purchase_basis': 10.0,
            'price_market': 12.0,
            'is_wotc': False,
        })
        prices = self.config.apply_formula(card)
        # 10.0 * 0.80 = 8.0, rounded to 0.05 = 8.00
        self.assertEqual(prices['credit_purchase_price'], 8.0)

    def test_apply_formula_sales_with_floor(self):
        """Test sales price respects category floor."""
        card = self.env['supertcg.batch.card'].new({
            'condition': 'nm',
            'card_category': 'holo',
            'language': 'en',
            'purchase_basis': 0.5,
            'price_market': 0.5,
            'is_wotc': False,
        })
        prices = self.config.apply_formula(card)
        # Market-based: 0.5 * 1.20 = 0.60, rounded = 0.60
        # Floor for holo: 1.0
        # Sales = max(0.60, 1.0) = 1.0
        self.assertEqual(prices['sales_price'], 1.0)

    def test_apply_formula_sales_above_floor(self):
        """Test sales price when market-based exceeds floor."""
        card = self.env['supertcg.batch.card'].new({
            'condition': 'nm',
            'card_category': 'holo',
            'language': 'en',
            'purchase_basis': 10.0,
            'price_market': 10.0,
            'is_wotc': False,
        })
        prices = self.config.apply_formula(card)
        # Market-based: 10.0 * 1.20 = 12.0, rounded = 12.0
        # Floor for holo: 1.0
        # Sales = max(12.0, 1.0) = 12.0
        self.assertEqual(prices['sales_price'], 12.0)

    def test_apply_formula_minimum_purchase(self):
        """Test purchase price respects minimum."""
        card = self.env['supertcg.batch.card'].new({
            'condition': 'nm',
            'card_category': 'common',
            'language': 'en',
            'purchase_basis': 0.01,
            'price_market': 0.01,
            'is_wotc': False,
        })
        prices = self.config.apply_formula(card)
        # 0.01 * 0.70 = 0.007, but min is 0.05
        self.assertEqual(prices['purchase_price'], 0.05)

    def test_wotc_set_codes_parsing(self):
        """Test WOTC set codes are parsed correctly."""
        codes = [c.strip() for c in self.config.wotc_set_codes.split(',')]
        self.assertIn('BS', codes)
        self.assertIn('JU', codes)
        self.assertIn('SK', codes)

    def test_company_unique_constraint(self):
        """Test only one pricing config per company is allowed."""
        from psycopg2 import IntegrityError
        # Create a fresh company that definitely has no config
        fresh_company = self.env['res.company'].create({'name': 'Fresh Test Company'})
        # First create should succeed
        config1 = self.env['supertcg.pricing.config'].create({
            'company_id': fresh_company.id,
        })
        self.assertTrue(config1)
        # Second create should fail with IntegrityError (SQL constraint)
        with self.assertRaises(IntegrityError):
            self.env['supertcg.pricing.config'].create({
                'company_id': fresh_company.id,
            })
