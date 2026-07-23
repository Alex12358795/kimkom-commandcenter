from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def _get_warehouse_availability(self):
        self.ensure_one()
        if len(self.product_variant_ids) == 1:
            return self.product_variant_ids._get_warehouse_availability()
        # For multi-variant products, aggregate warehouses where any variant has stock
        warehouses = {}
        for variant in self.product_variant_ids:
            for info in variant._get_warehouse_availability():
                wh = info["warehouse"]
                if wh.id not in warehouses:
                    warehouses[wh.id] = {"warehouse": wh, "qty": 0}
                warehouses[wh.id]["qty"] += info["qty"]
        return list(warehouses.values())

    def _get_website_max_qty(self):
        self.ensure_one()
        if len(self.product_variant_ids) == 1:
            return self.product_variant_ids._get_website_max_qty()
        # For multi-variant products, sum max qty across all variants
        total = 0
        for variant in self.product_variant_ids:
            total += variant._get_website_max_qty()
        return total

    def _get_pickup_max_qty(self):
        """Return max quantity available at a single store (for pickup)."""
        self.ensure_one()
        avail = self._get_warehouse_availability()
        if not avail:
            return 0
        return max(int(info["qty"]) for info in avail)
