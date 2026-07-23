from odoo import models, fields, api
import re

class EventRegistration(models.Model):
    _inherit = 'event.registration'

    payment_status = fields.Selection([
        ('pending', 'Pending Payment'),
        ('paid', 'Paid'),
    ], string='Payment Status', default='pending', index=True)
    
    pos_order_id = fields.Many2one(
        'pos.order',
        string='POS Order',
        help='Linked POS order for venue payments'
    )
    
    pay_at_venue = fields.Boolean(
        string='Pay at Venue',
        default=False,
        help='Registration was made with Pay at Venue option'
    )
    
    def _auto_init(self):
        """Ensure custom columns exist. Safety net for failed upgrades."""
        cr = self.env.cr
        columns = [
            ('payment_status', 'VARCHAR'),
            ('pos_order_id', 'INTEGER'),
            ('pay_at_venue', 'BOOLEAN'),
        ]
        for col_name, col_type in columns:
            cr.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'event_registration' AND column_name = %s
            """, (col_name,))
            if not cr.fetchone():
                cr.execute(
                    "ALTER TABLE event_registration ADD COLUMN {} {}".format(col_name, col_type)
                )
        super()._auto_init()

    def _get_registration_summary(self):
        """Override to include payment status"""
        res = super()._get_registration_summary()
        res.update({
            'payment_status': self.payment_status,
            'has_to_pay': self.payment_status == 'pending',
        })
        return res
    
    @api.model
    def register_attendee(self, barcode, event_id):
        """Override to block check-in for unpaid registrations"""
        result = super().register_attendee(barcode, event_id)
        
        if not result.get('error'):
            attendee = self.search([('barcode', '=', barcode)], limit=1)
            if attendee and attendee.payment_status == 'pending':
                # Override status to show payment needed
                result['status'] = 'need_payment'
                result['payment_status'] = 'pending'
                result['event_fee'] = attendee.event_id.event_fee
        
        return result
