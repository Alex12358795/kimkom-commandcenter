from odoo import models, fields


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    signature_data = fields.Binary(
        string='Customer Signature',
        attachment=False,
        help='Base64-encoded PNG signature captured during buy-in.',
    )
