from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _is_add_to_cart_possible(self, parent_combination=None):
        self.ensure_one()
        if not self.product_tmpl_id.sale_ok:
            return False
        if self.allow_out_of_stock_order:
            return True
        # Check standard stock (uses default warehouse context)
        if self.free_qty > 0:
            return True
        # Check if any store warehouse has stock
        store_warehouses = self.env["stock.warehouse"].browse([5, 6, 7, 8])
        for wh in store_warehouses:
            if self.with_context(warehouse_id=wh.id).free_qty > 0:
                return True
        return False

    def _get_warehouse_availability(self):
        self.ensure_one()
        store_warehouses = self.env["stock.warehouse"].browse([5, 6, 7, 8])
        result = []
        for wh in store_warehouses:
            qty = self.with_context(warehouse_id=wh.id).free_qty
            if qty > 0:
                result.append({"warehouse": wh, "qty": qty})
        return result

    def _get_website_max_qty(self):
        self.ensure_one()
        store_warehouses = self.env["stock.warehouse"].browse([5, 6, 7, 8])
        total = 0
        for wh in store_warehouses:
            qty = self.with_context(warehouse_id=wh.id).free_qty
            if qty > 0:
                total += qty
        return total or 1
