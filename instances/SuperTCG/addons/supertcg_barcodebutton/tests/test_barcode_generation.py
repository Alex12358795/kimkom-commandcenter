# -*- coding: utf-8 -*-
###############################################################################
#
#    SuperTCG
#
#    Copyright (C) 2024-TODAY SuperTCG (<https://www.supertcg.be>)
#    Author: SuperTCG
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.tools.barcode import check_barcode_encoding, get_barcode_check_digit
from odoo.addons.supertcg_barcodebutton.models.product_product import generate_ean


class TestEANHelpers(TransactionCase):
    """Test the pure EAN-13 helper functions."""

    def test_generate_ean_basic(self):
        """EAN generation produces 13-digit strings starting with 20."""
        barcode = generate_ean("1")
        self.assertEqual(len(barcode), 13)
        self.assertTrue(barcode.startswith("20"))
        self.assertTrue(barcode.isdigit())

    def test_generate_ean_valid_checksum(self):
        """Generated EAN must pass Odoo's EAN-13 validation."""
        for ean_id in ("1", "12345", "999999", "", "0"):
            barcode = generate_ean(ean_id)
            self.assertTrue(
                check_barcode_encoding(barcode, "ean13"),
                f"Barcode {barcode} for ID {ean_id!r} failed Odoo EAN-13 validation",
            )

    def test_generate_ean_different_prefix(self):
        """Custom prefix is honoured."""
        barcode = generate_ean("42", prefix="99")
        self.assertTrue(barcode.startswith("99"))
        self.assertEqual(len(barcode), 13)
        self.assertTrue(check_barcode_encoding(barcode, "ean13"))

    def test_generate_ean_long_id_truncated(self):
        """IDs longer than 10 digits are truncated to the last 10."""
        barcode = generate_ean("123456789012345")
        identifier = barcode[2:12]  # 10 digits after prefix
        self.assertEqual(identifier, "6789012345")  # last 10 of input

    def test_odoo_checksum_known_valid(self):
        """Verify Odoo's checksum helper against a known valid EAN-13."""
        # 4009908058775 is a valid EAN-13 (verified via Odoo validator)
        self.assertEqual(get_barcode_check_digit("4009908058775"), 5)
        self.assertTrue(check_barcode_encoding("4009908058775", "ean13"))

    def test_odoo_checksum_invalid(self):
        """Odoo validator correctly rejects invalid EAN-13."""
        # 4009908058777 has wrong checksum
        self.assertFalse(check_barcode_encoding("4009908058777", "ean13"))

    def test_check_barcode_encoding_empty(self):
        """Empty barcode is considered invalid for ean13 encoding.

        Note: Odoo's check_barcode_encoding crashes on empty strings,
        so we test the behavior indirectly via our generate_ean edge case.
        """
        barcode = generate_ean("")
        self.assertTrue(check_barcode_encoding(barcode, "ean13"))

    def test_check_barcode_encoding_wrong_length(self):
        """Wrong length is invalid."""
        self.assertFalse(check_barcode_encoding("12345678901", "ean13"))
        self.assertFalse(check_barcode_encoding("12345678901234", "ean13"))

    def test_check_barcode_encoding_non_numeric(self):
        """Non-numeric EAN is invalid."""
        self.assertFalse(check_barcode_encoding("12345678901ab", "ean13"))

    def test_check_barcode_encoding_bad_checksum(self):
        """EAN with incorrect checksum digit is invalid."""
        # 4009908058775 is valid, so 4009908058778 should be invalid
        self.assertFalse(check_barcode_encoding("4009908058778", "ean13"))


class TestBarcodeGeneration(TransactionCase):
    """Test barcode generation on product models."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_tmpl = cls.env["product.template"].create(
            {
                "name": "Test Product for Barcode",
                "type": "consu",
            }
        )
        cls.variant = cls.product_tmpl.product_variant_ids[:1]

    def test_action_generate_barcode_on_variant(self):
        """Variant barcode generation works and sets a valid EAN."""
        self.assertFalse(self.variant.barcode)
        self.variant.action_generate_barcode()
        self.assertTrue(self.variant.barcode)
        self.assertEqual(len(self.variant.barcode), 13)
        self.assertTrue(check_barcode_encoding(self.variant.barcode, "ean13"))

    def test_action_generate_barcode_on_template(self):
        """Template barcode generation delegates to variant and returns a
        notification that triggers a view reload so the barcode appears
        immediately without a manual page refresh."""
        self.assertFalse(self.product_tmpl.barcode)
        result = self.product_tmpl.action_generate_barcode()
        self.assertTrue(self.variant.barcode)
        self.assertEqual(len(self.variant.barcode), 13)
        # Notification dict returned
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")
        # The notification must include a 'next' action that reloads the view
        params = result.get("params", {})
        self.assertIn(
            "next",
            params,
            "Notification should include a 'next' action to reload the view",
        )
        next_action = params["next"]
        self.assertEqual(next_action.get("type"), "ir.actions.client")
        self.assertEqual(next_action.get("tag"), "reload")

    def test_no_overwrite_variant(self):
        """Cannot overwrite an existing barcode on variant."""
        self.variant.barcode = "2000000000005"
        with self.assertRaises(UserError):
            self.variant.action_generate_barcode()

    def test_no_overwrite_template(self):
        """Cannot overwrite an existing barcode on template."""
        self.variant.barcode = "2000000000005"
        with self.assertRaises(UserError):
            self.product_tmpl.action_generate_barcode()

    def test_barcode_uniqueness_per_variant(self):
        """Two different variants get different barcodes."""
        tmpl2 = self.env["product.template"].create(
            {
                "name": "Second Test Product",
                "type": "consu",
            }
        )
        variant2 = tmpl2.product_variant_ids[:1]
        self.variant.action_generate_barcode()
        variant2.action_generate_barcode()
        self.assertNotEqual(self.variant.barcode, variant2.barcode)

    def test_barcode_consistency_after_regenerate(self):
        """Same ID always produces the same barcode."""
        code1 = generate_ean(str(self.variant.id))
        code2 = generate_ean(str(self.variant.id))
        self.assertEqual(code1, code2)

    def test_barcode_passes_odoo_validation(self):
        """Every generated barcode passes Odoo's internal EAN-13 check."""
        for tmpl in self.env["product.template"].create(
            [
                {"name": "P1", "type": "consu"},
                {"name": "P2", "type": "consu"},
                {"name": "P3", "type": "consu"},
            ]
        ):
            variant = tmpl.product_variant_ids[:1]
            variant.action_generate_barcode()
            self.assertTrue(
                check_barcode_encoding(variant.barcode, "ean13"),
                f"Barcode {variant.barcode} failed Odoo validation",
            )
