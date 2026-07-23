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


class ProductTemplate(models.Model):
    """Inherit product_template to expose manual barcode generation."""

    _inherit = "product.template"

    def action_generate_barcode(self):
        """Generate an internal (non-certified) EAN-13 style barcode.

        The barcode is generated on the first product variant. If the product
        already carries a barcode, the user must clear it first.
        """
        self.ensure_one()
        if self.barcode:
            raise UserError(
                _(
                    "This product already has a barcode. Please remove the old barcode first."
                )
            )
        variant = self.product_variant_ids[:1]
        if not variant:
            raise UserError(_("No product variant found for this product."))
        variant.action_generate_barcode()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Barcode generated successfully: %s", variant.barcode),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "reload",
                },
            },
        }
