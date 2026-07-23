from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _cart_update(self, product_id, line_id=None, add_qty=0, set_qty=0, **kwargs):
        # Convert string parameters from web forms to numbers
        try:
            add_qty = float(add_qty) if add_qty else 0
        except (ValueError, TypeError):
            add_qty = 0
        if set_qty is not None:
            try:
                set_qty = float(set_qty)
            except (ValueError, TypeError):
                set_qty = 0
        else:
            set_qty = 0

        product = self.env["product.product"].browse(product_id)
        if product.exists() and product.is_storable:
            max_qty = product._get_website_max_qty()
            # Find existing quantity for this product in cart
            existing_qty = 0
            if line_id:
                line = self.env["sale.order.line"].browse(line_id)
                if line.exists():
                    existing_qty = line.product_uom_qty
            if existing_qty == 0 and self.order_line:
                for line in self.order_line.filtered(
                    lambda l: l.product_id.id == product_id and not l.is_delivery
                ):
                    existing_qty += line.product_uom_qty
            # Silently cap quantity instead of raising error
            if set_qty > 0:
                set_qty = min(set_qty, max_qty)
            elif add_qty > 0:
                add_qty = min(add_qty, max(0, max_qty - existing_qty))

        result = super()._cart_update(
            product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, **kwargs
        )

        # Route order to warehouse that actually has stock
        line = self.order_line.filtered(
            lambda l: l.product_id.id == product_id and not l.is_delivery
        )
        if line and line.suggested_warehouse_id:
            self.warehouse_id = line.suggested_warehouse_id

        return result

    def _get_warehouse_count(self):
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: l.product_id and not l.is_delivery)
        if not lines:
            return 1
        warehouses = lines.mapped("suggested_warehouse_id")
        return len(warehouses) or 1

    def _create_delivery_line(self, carrier, price_unit):
        warehouse_count = self._get_warehouse_count()
        if warehouse_count > 1:
            price_unit = price_unit * warehouse_count
        return super()._create_delivery_line(carrier, price_unit)
