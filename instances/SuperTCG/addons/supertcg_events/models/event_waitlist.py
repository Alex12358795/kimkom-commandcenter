from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class EventWaitlist(models.Model):
    _name = 'event.waitlist'
    _description = 'Event Waitlist Entry'
    _order = 'create_date asc, id asc'
    _rec_name = 'email'

    event_id = fields.Many2one(
        'event.event',
        string='Event',
        required=True,
        ondelete='cascade',
        index=True
    )
    
    name = fields.Char(
        string='Name',
        required=True
    )
    
    email = fields.Char(
        string='Email',
        required=True
    )
    
    phone = fields.Char(
        string='Phone'
    )
    
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('notified', 'Notified'),
        ('registered', 'Registered'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='waiting', required=True, index=True)
    
    notes = fields.Text(
        string='Notes'
    )
    
    notified_date = fields.Datetime(
        string='Notified On'
    )
    
    def action_register_attendee(self):
        """Move waitlist entry to actual event registration.
        
        Permanently increases the event limit by 1 to reflect the additional attendee.
        This is the cleanest approach - no SQL hacks, no cache issues, no validation errors.
        """
        self.ensure_one()
        if self.state == 'registered':
            raise ValidationError(_('Deze persoon is al geregistreerd.'))
        
        event = self.event_id
        
        # Permanently increase limit by 1 (reflects reality: N+1 attendees now)
        event.sudo().write({
            'seats_max': event.seats_max + 1
        })
        
        # Create registration normally through ORM
        self.env['event.registration'].sudo().create({
            'event_id': event.id,
            'name': self.name,
            'email': self.email,
            'phone': self.phone,
            'state': 'open',
        })
        
        # Mark waitlist entry as registered
        self.write({
            'state': 'registered',
            'notified_date': fields.Datetime.now(),
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Wachtlijst',
            'res_model': 'event.waitlist',
            'view_mode': 'list,form',
            'domain': [('event_id', '=', self.event_id.id)],
            'context': {'default_event_id': self.event_id.id},
            'target': 'current',
        }
    
    @api.constrains('email')
    def _check_email(self):
        for record in self:
            if record.email and '@' not in record.email:
                raise ValidationError(_('Please enter a valid email address.'))
    
    _sql_constraints = [
        ('unique_event_email', 'unique(event_id, email)', 
         _('This email is already on the waiting list for this event.'))
    ]
