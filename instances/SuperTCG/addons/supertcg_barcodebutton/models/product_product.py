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
from odoo import models, _
from odoo.exceptions import UserError
from odoo.tools.barcode import check_barcode_encoding, get_barcode_check_digit


class ProductProduct(models.Model):
    """Inherit product_product model for adding internal EAN-13 style barcode."""

    _inherit = "product.product"

    def action_generate_barcode(self):
        """Generate an internal (non-certified) EAN-13 style barcode for this variant."""
        self.ensure_one()
        if self.barcode:
            raise UserError(
                _(
                    "This product already has a barcode. Please remove the old barcode first."
                )
            )
        barcode = generate_ean(str(self.id))
        if not check_barcode_encoding(barcode, "ean13"):
            raise UserError(
                _("Generated barcode '%s' failed EAN-13 validation.", barcode)
            )
        self.barcode = barcode
        return True


def generate_ean(ean, prefix="20"):
    """Generate an internal (non-certified) EAN-13 style barcode.

    Uses the given prefix (default ``20`` — *not* a real GS1 country/prefix
    code and does **not** collide with Odoo POS weight-barcode rules) followed
    by a 10-digit identifier based on the product ID, plus a valid EAN-13
    checksum computed via Odoo's own ``get_barcode_check_digit``.

    :param ean: Identifier string (typically the product database ID).
    :param prefix: 2-digit prefix (default ``20``).
    :return: 13-digit string with a valid EAN-13 checksum.
    """
    if not ean:
        ean = "0"
    # Build a 10-digit identifier, zero-padded, taking the last 10 digits.
    identifier = str(ean).zfill(10)[-10:]
    # prefix (2) + identifier (10) = 12 digits before checksum
    base = prefix + identifier
    # Compute checksum using Odoo's GS1-compliant helper.
    # We append '0' as a placeholder check digit so Odoo removes it
    # and recomputes the correct one based on the full 12-digit base.
    checksum = get_barcode_check_digit(base + "0")
    return f"{base}{checksum}"
