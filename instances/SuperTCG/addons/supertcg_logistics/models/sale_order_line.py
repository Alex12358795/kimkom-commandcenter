from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    suggested_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Suggested Warehouse",
        compute="_compute_suggested_warehouse_id",
        store=True,
    )

    @api.depends("product_id")
    def _compute_suggested_warehouse_id(self):
        store_warehouses = self.env["stock.warehouse"].browse([5, 6, 7, 8])
        for line in self:
            if not line.product_id:
                line.suggested_warehouse_id = False
                continue
            best_wh = False
            best_qty = -1
            for wh in store_warehouses:
                qty = line.product_id.with_context(warehouse_id=wh.id).free_qty
                if qty > best_qty:
                    best_qty = qty
                    best_wh = wh
            line.suggested_warehouse_id = best_wh
