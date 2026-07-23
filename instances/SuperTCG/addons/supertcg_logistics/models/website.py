from odoo import models


class Website(models.Model):
    _inherit = "website"

    def _get_product_available_qty(self, product, **kwargs):
        website = self.get_current_website()
        # If website has explicit warehouse set, use standard behavior
        if website.warehouse_id:
            return super()._get_product_available_qty(product, **kwargs)
        # Sum free_qty across all store warehouses
        store_warehouses = self.env["stock.warehouse"].browse([5, 6, 7, 8])
        total = 0
        for wh in store_warehouses:
            qty = product.with_context(warehouse_id=wh.id).free_qty
            if qty > 0:
                total += qty
        return total
