from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Add 'product' (Storable Product) back to the type selection
    # The atharva_theme_base module removed it, but stock quants require it
    type = fields.Selection([
        ('consu', 'Goods'),
        ('service', 'Service'),
        ('combo', 'Combo'),
        ('product', 'Storable Product'),
    ], string='Product Type', default='consu', required=True)
