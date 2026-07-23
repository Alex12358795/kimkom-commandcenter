import logging
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError

logger = logging.getLogger(__name__)


class TcgConsignmentSettlement(models.Model):
    _name = 'tcg.consignment.settlement'
    _description = 'Consignment Settlement'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default='New',
    )
    partner_id = fields.Many2one(
        'res.partner', string='Consignment Owner',
        required=True, tracking=True,
        domain=[('supplier_rank', '>', 0)],
    )
    date_from = fields.Date(
        string='Date From', tracking=True,
        help='Only include items sold after this date.',
    )
    date_to = fields.Date(
        string='Date To', default=fields.Date.today, tracking=True,
        help='Only include items sold before this date.',
    )
    line_ids = fields.One2many(
        'tcg.consignment.settlement.line', 'settlement_id',
        string='Settlement Lines',
    )
    invoice_id = fields.Many2one(
        'account.move', string='Vendor Bill', readonly=True, tracking=True,
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('invoiced', 'Invoiced'), ('paid', 'Paid')],
        default='draft', required=True, tracking=True,
    )
    total_amount = fields.Float(
        string='Total Settlement', compute='_compute_total_amount',
        store=True, tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
    )

    @api.depends('line_ids.settlement_amount')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('settlement_amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'tcg.consignment.settlement'
                ) or 'New'
        return super().create(vals_list)

    def action_fetch_sold_items(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only fetch items in Draft state.'))
        if not self.partner_id:
            raise UserError(_('Please select a consignment owner first.'))

        receipt_moves = self.env['stock.move'].search([
            ('restrict_partner_id', '=', self.partner_id.id),
            ('picking_id.origin', 'ilike', 'TCG Consignment'),
            ('state', '=', 'done'),
        ])

        product_received = {}
        product_cost = {}
        consignment_product_ids = []
        for move in receipt_moves:
            pid = move.product_id.id
            product_received[pid] = product_received.get(pid, 0) + move.product_uom_qty
            product_cost[pid] = move.price_unit or move.product_id.standard_price
            consignment_product_ids.append(pid)

        if not consignment_product_ids:
            raise UserError(_(
                'No consignment receipts found for %s.'
            ) % self.partner_id.name)

        settled_product_ids = set(self.env['tcg.consignment.settlement.line'].search([
            ('settlement_id.partner_id', '=', self.partner_id.id),
        ]).mapped('product_id.id'))

        delivery_moves = self.env['stock.move'].search([
            ('product_id', 'in', consignment_product_ids),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
        ])
        product_delivered = {}
        for move in delivery_moves:
            product_delivered[move.product_id.id] = product_delivered.get(move.product_id.id, 0) + move.product_uom_qty

        lines_vals = []
        for product_id, received_qty in product_received.items():
            if product_id in settled_product_ids:
                continue
            delivered_qty = product_delivered.get(product_id, 0)
            sold_qty = min(received_qty, delivered_qty)
            if sold_qty > 0:
                product = self.env['product.product'].browse(product_id)
                sale_price = product.list_price
                cost_price = product_cost.get(product_id, product.standard_price)
                sale_ref = self._find_sale_reference(product_id)
                lines_vals.append({
                    'product_id': product_id,
                    'qty': sold_qty,
                    'sale_price': sale_price,
                    'cost_price': cost_price,
                    'sale_reference': sale_ref,
                })

        if not lines_vals:
            raise UserError(_(
                'No unsettled sold consignment items found for %s.'
            ) % self.partner_id.name)

        self.line_ids = [(5, 0, 0)] + [(0, 0, lv) for lv in lines_vals]
        self.message_post(body=_(
            'Fetched %d sold consignment item(s) for %s.'
        ) % (len(lines_vals), self.partner_id.name))

    def _find_sale_reference(self, product_id):
        delivery_moves = self.env['stock.move'].search([
            ('product_id', '=', product_id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
        ], limit=1)
        if delivery_moves:
            picking = delivery_moves.picking_id
            if hasattr(picking, 'pos_order_id') and picking.pos_order_id:
                return picking.pos_order_id.name
            if delivery_moves.sale_line_id:
                return delivery_moves.sale_line_id.order_id.name
            return picking.name or ''
        return ''

    def action_create_invoice(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Invoice can only be created in Draft state.'))
        if not self.line_ids:
            raise UserError(_('No settlement lines. Fetch sold items first.'))

        journal = self.env['account.journal'].search([
            ('name', '=', 'Second hand purchases'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'Second hand purchases',
                'code': 'SHP',
                'type': 'purchase',
                'company_id': self.env.company.id,
            })

        purchase_tax = self.env['account.tax'].search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
        ], limit=1)

        expense_account = self.env['account.account'].search([
            ('code_store', 'ilike', '%604000%'),
            ('account_type', '=', 'expense'),
        ], limit=1)
        if not expense_account:
            expense_account = self.env['account.account'].search([
                ('code_store', 'ilike', '%600000%'),
                ('account_type', '=', 'expense'),
            ], limit=1)

        invoice_lines = []
        for line in self.line_ids:
            tax_ids = [(6, 0, [purchase_tax.id])] if purchase_tax else []
            line_vals = {
                'name': _('Consignment settlement: %s') % line.product_id.display_name,
                'product_id': line.product_id.id,
                'quantity': line.qty,
                'price_unit': line.cost_price,
                'tax_ids': tax_ids,
            }
            if expense_account:
                line_vals['account_id'] = expense_account.id
            invoice_lines.append((0, 0, line_vals))

        invoice = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'partner_id': self.partner_id.id,
            'journal_id': journal.id,
            'invoice_date': date.today(),
            'invoice_line_ids': invoice_lines,
        })
        invoice.action_post()

        self.write({
            'invoice_id': invoice.id,
            'state': 'invoiced',
        })
        self.message_post(body=_(
            'Vendor bill %s created for €%.2f.'
        ) % (invoice.name, self.total_amount))

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_('No invoice linked to this settlement.'))
        action = self.env.ref('account.action_move_in_invoice_type')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
            'target': 'current',
        }

    def action_mark_paid(self):
        self.ensure_one()
        if self.state != 'invoiced':
            raise UserError(_('Can only mark as Paid from Invoiced state.'))
        if self.invoice_id and self.invoice_id.payment_state == 'paid':
            self.state = 'paid'
            self.message_post(body=_('Settlement marked as paid.'))
        elif self.invoice_id:
            raise UserError(_(
                'Vendor bill is not fully paid yet (state: %s). '
                'Please register payment first.'
            ) % self.invoice_id.payment_state)
        else:
            self.state = 'paid'
            self.message_post(body=_('Settlement marked as paid (no bill linked).'))


class TcgConsignmentSettlementLine(models.Model):
    _name = 'tcg.consignment.settlement.line'
    _description = 'Consignment Settlement Line'

    settlement_id = fields.Many2one(
        'tcg.consignment.settlement', string='Settlement',
        required=True, ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, readonly=True,
    )
    product_name = fields.Char(
        related='product_id.display_name', string='Product Name',
    )
    qty = fields.Float(string='Quantity', default=1.0, readonly=True)
    sale_price = fields.Float(
        string='Sale Price', readonly=True,
        help='Price at which the item was sold.',
    )
    cost_price = fields.Float(
        string='Settlement Price', readonly=True,
        help='Original consignment cost (owed to owner).',
    )
    settlement_amount = fields.Float(
        string='Amount', compute='_compute_settlement_amount',
        store=True,
    )
    move_line_id = fields.Many2one(
        'stock.move.line', string='Delivery Line', readonly=True,
    )
    sale_reference = fields.Char(
        string='Sale Reference', readonly=True,
        help='POS order or SO reference.',
    )

    @api.depends('qty', 'cost_price')
    def _compute_settlement_amount(self):
        for rec in self:
            rec.settlement_amount = rec.qty * rec.cost_price
