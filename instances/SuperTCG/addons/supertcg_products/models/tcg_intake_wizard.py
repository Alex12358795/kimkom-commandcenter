import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

AANKOOP_PRODUCT_NAME = 'Aankoop 2dehands'


class TcgIntakeWizard(models.TransientModel):
    _name = 'tcg.intake.wizard'
    _description = 'TCG Intake Wizard'

    intake_type = fields.Selection(
        [('buy_in', 'Buy-in'), ('consignment', 'Consignment')],
        required=True, default='buy_in',
    )
    partner_id = fields.Many2one('res.partner', required=True)
    picking_type_id = fields.Many2one(
        'stock.picking.type', required=True,
        domain="[('code', '=', 'incoming')]",
    )
    employee_id = fields.Many2one('hr.employee', string='Employee')
    product_qty = fields.Float(string='Quantity', default=1.0)
    price_unit = fields.Float(string='Unit Price', default=0.0)
    consignment_enabled = fields.Boolean(compute='_compute_consignment_enabled')

    @api.depends('intake_type')
    def _compute_consignment_enabled(self):
        group = self.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
        for wizard in self:
            wizard.consignment_enabled = bool(group and group in self.env.user.groups_id)

    def action_cancel(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/tcg/aankoop',
            'target': 'self',
        }

    def action_start_intake(self):
        self.ensure_one()
        if self.intake_type == 'consignment':
            self._check_consignment_enabled()
            picking = self._create_consignment_picking()
            return self._redirect_to_intake_form('picking', picking.id, self.partner_id.id)
        else:
            po = self._create_purchase_order()
            return self._redirect_to_intake_form('po', po.id, self.partner_id.id)

    def _check_consignment_enabled(self):
        group = self.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
        if not group or group not in self.env.user.groups_id:
            raise ValidationError(_(
                "Consignment tracking is not enabled. Please enable it in "
                "Inventory \u203a Settings \u203a Consignment (Owned Stock)."
            ))

    def _get_or_create_aankoop_product(self):
        product = self.env['product.product'].search([
            ('name', '=', AANKOOP_PRODUCT_NAME),
        ], limit=1)
        if product:
            return product
        purchase_tax = self.env['account.tax'].search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
        ], limit=1)
        template = self.env['product.template'].create({
            'name': AANKOOP_PRODUCT_NAME,
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': False,
            'is_storable': False,
            'supplier_taxes_id': [(6, 0, [purchase_tax.id])] if purchase_tax else False,
        })
        product = template.product_variant_id
        logger.info('Created Aankoop 2dehands product (id=%d)', product.id)
        return product

    def _create_consignment_picking(self):
        picking_vals = {
            'picking_type_id': self.picking_type_id.id,
            'partner_id': self.partner_id.id,
            'owner_id': self.partner_id.id,
            'location_id': self.picking_type_id.default_location_src_id.id,
            'location_dest_id': self.picking_type_id.default_location_dest_id.id,
            'origin': 'TCG Consignment - %s' % self.partner_id.name,
        }
        picking = self.env['stock.picking'].create(picking_vals)
        logger.info('Created consignment picking %s for partner %s', picking.name, self.partner_id.name)
        return picking

    def _create_purchase_order(self):
        employee_name = self.employee_id.name if self.employee_id else ''
        origin_parts = ['Buy-in']
        if employee_name:
            origin_parts.append(employee_name)
        origin = ' - '.join(origin_parts)

        po_vals = {
            'partner_id': self.partner_id.id,
            'picking_type_id': self.picking_type_id.id,
            'origin': origin,
        }
        po = self.env['purchase.order'].create(po_vals)

        product = self._get_or_create_aankoop_product()
        purchase_tax = self.env['account.tax'].search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
        ], limit=1)

        line_vals = {
            'order_id': po.id,
            'product_id': product.id,
            'name': AANKOOP_PRODUCT_NAME,
            'product_qty': self.product_qty or 1.0,
            'price_unit': self.price_unit or 0.0,
            'product_uom': product.uom_id.id,
        }
        if purchase_tax:
            line_vals['taxes_id'] = [(6, 0, [purchase_tax.id])]
        self.env['purchase.order.line'].create(line_vals)

        logger.info('Created purchase order %s for partner %s (origin=%s)', po.name, self.partner_id.name, origin)
        return po

    def _redirect_to_intake_form(self, source_type, source_doc_id, partner_id):
        if source_type == 'po':
            url = '/web#model=purchase.order&id=%d&view_type=form' % source_doc_id
        elif source_type == 'picking':
            url = '/web#model=stock.picking&id=%d&view_type=form' % source_doc_id
        else:
            url = '/tcg/aankoop'
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'self',
        }
