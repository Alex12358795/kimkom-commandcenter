from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class EventEvent(models.Model):
    _inherit = 'event.event'

    is_recurring_template = fields.Boolean(
        string='Is Recurring Template',
        default=False,
        help='Automatically set when event is in "Recurring Template" stage'
    )
    
    recurrence_pattern = fields.Selection([
        ('weekly', 'Weekly'),
        ('bi_weekly', 'Bi-weekly'),
    ], string='Recurrence Pattern', default='weekly')
    
    template_id = fields.Many2one(
        'event.event',
        string='Template Event',
        help='Link to the template event (for copied events)'
    )
    
    last_copied_date = fields.Date(
        string='Last Copied Date',
        help='Date when this template was last copied'
    )
    
    copy_count = fields.Integer(
        string='Copy Count',
        default=0,
        help='Number of times this event has been copied'
    )
    
    waitlist_ids = fields.One2many(
        'event.waitlist',
        'event_id',
        string='Waitlist Entries'
    )
    
    waitlist_count = fields.Integer(
        string='Waitlist Count',
        compute='_compute_waitlist_count',
        store=True
    )
    
    allow_pay_at_venue = fields.Boolean(
        string='Allow Pay at Venue',
        default=False,
        help='Allow attendees to register online and pay at the venue'
    )

    event_fee = fields.Float(
        string='Event Fee',
        default=0.0,
        help='Flat fee amount for this event (used for pay-at-venue calculations)'
    )

    has_paid_tickets = fields.Boolean(
        string='Has Paid Tickets',
        compute='_compute_has_paid_tickets',
        store=True
    )
    
    @api.depends('event_ticket_ids', 'event_ticket_ids.price')
    def _compute_has_paid_tickets(self):
        for event in self:
            event.has_paid_tickets = any(ticket.price > 0 for ticket in event.event_ticket_ids)
    
    @api.depends('waitlist_ids', 'waitlist_ids.state')
    def _compute_waitlist_count(self):
        for event in self:
            event.waitlist_count = len(event.waitlist_ids.filtered(lambda w: w.state in ['waiting', 'notified']))
    
    def write(self, vals):
        # Sync is_recurring_template with stage
        if 'stage_id' in vals:
            template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
            if template_stage:
                vals['is_recurring_template'] = vals['stage_id'] == template_stage.id
            else:
                vals['is_recurring_template'] = False
        return super(EventEvent, self).write(vals)
    
    @api.model_create_multi
    def create(self, vals_list):
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        for vals in vals_list:
            if 'stage_id' in vals and template_stage:
                vals['is_recurring_template'] = vals['stage_id'] == template_stage.id
        return super(EventEvent, self).create(vals_list)

    def action_generate_weekly_copies(self):
        """Manual action to generate weekly copies for this template"""
        self.ensure_one()
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        if not template_stage or self.stage_id.id != template_stage.id:
            raise UserError(_('This event is not in "Recurring Template" stage. Move it to that stage first.'))
        
        copies = self._create_weekly_copies(weeks_ahead=4)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Created %s weekly event copies.') % len(copies),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_preview_next_copies(self):
        """Preview what copies would be created without creating them"""
        self.ensure_one()
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        if not template_stage or self.stage_id.id != template_stage.id:
            raise UserError(_('This event is not in "Recurring Template" stage. Move it to that stage first.'))
        
        preview_dates = self._get_next_copy_dates(weeks_ahead=4)
        message = _('Next 4 copies would be created for:<br/>')
        for date in preview_dates:
            message += _('• %s<br/>') % date.strftime('%d/%m/%Y')
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Preview'),
                'message': message,
                'type': 'info',
                'sticky': True,
            }
        }

    def _get_next_copy_dates(self, weeks_ahead=4):
        """Calculate the next copy dates based on the template's weekday"""
        self.ensure_one()
        
        # Get the weekday from the template's date_begin
        template_weekday = self.date_begin.weekday()
        
        today = datetime.now().date()
        next_dates = []
        
        for week in range(1, weeks_ahead + 1):
            # Calculate next occurrence of this weekday
            days_until_next = (template_weekday - today.weekday()) % 7
            if days_until_next == 0:
                days_until_next = 7  # If today is the same weekday, go to next week
            
            next_date = today + timedelta(days=days_until_next + (week - 1) * 7)
            next_dates.append(next_date)
        
        return next_dates

    def _create_weekly_copies(self, weeks_ahead=4):
        """Create weekly copies of this template event"""
        self.ensure_one()
        
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        if not template_stage or self.stage_id.id != template_stage.id:
            return []
        
        copies = []
        next_dates = self._get_next_copy_dates(weeks_ahead)
        
        for next_date in next_dates:
            # Check if copy already exists for this date
            existing = self.env['event.event'].search([
                ('template_id', '=', self.id),
                ('date_begin', '>=', datetime.combine(next_date, datetime.min.time())),
                ('date_begin', '<', datetime.combine(next_date + timedelta(days=1), datetime.min.time())),
            ], limit=1)
            
            if existing:
                continue
            
            # Calculate new dates
            original_date = self.date_begin.date()
            date_diff = next_date - original_date
            
            new_date_begin = self.date_begin + timedelta(days=date_diff.days)
            new_date_end = self.date_end + timedelta(days=date_diff.days)
            
            # Format name with date
            formatted_date = next_date.strftime('%d/%m/%Y')
            new_name = f"{self.name} - {formatted_date}"
            
            # Build copy values dynamically, only including fields that exist
            copy_vals = {
                'name': new_name,
                'date_begin': new_date_begin,
                'date_end': new_date_end,
                'template_id': self.id,
                'is_recurring_template': False,
                'address_id': self.address_id.id,
                'company_id': self.company_id.id,
                'organizer_id': self.organizer_id.id,
                'event_type_id': self.event_type_id.id,
                'user_id': self.user_id.id,
                'seats_limited': self.seats_limited,
                'seats_max': self.seats_max,
                'note': self.note,
                'description': self.description,
                'is_published': True,
                'date_tz': self.date_tz,
                'cover_properties': self.cover_properties,
                'website_meta_title': self.website_meta_title,
                'website_meta_description': self.website_meta_description,
                'website_meta_keywords': self.website_meta_keywords,
                'allow_pay_at_venue': self.allow_pay_at_venue,
            }
            
            # Dynamically add optional fields if they exist on the model
            optional_fields = [
                # Image fields
                'image_1024', 'badge_image',
                # Content fields
                'subtitle', 'lang', 'seo_name', 'ticket_instructions',
                # Website configuration
                'website_id', 'website_visibility', 'website_menu',
                'introduction_menu', 'location_menu', 'register_menu', 'community_menu',
                # Feature toggles (future-proof)
                'website_track', 'website_track_proposal',
                'exhibitor_menu', 'booth_menu', 'meeting_room_allow_creation',
                # Badge/Ticket configuration
                'badge_format', 'registration_properties_definition',
            ]
            
            for field_name in optional_fields:
                if field_name in self._fields:
                    field = self._fields[field_name]
                    value = self[field_name]
                    # Handle Many2one fields (need .id)
                    if field.type == 'many2one' and value:
                        copy_vals[field_name] = value.id
                    else:
                        copy_vals[field_name] = value
            
            copy = self.create(copy_vals)
            copies.append(copy)
            _logger.info(f"Created event copy: {copy.name} for date {next_date}")
            
            # Copy tickets from template to the new event
            # (self.create() does NOT copy One2many fields like event_ticket_ids)
            # Ensure copied products get the Events category, not "All"
            events_categ = self.env['product.category'].search([
                ('complete_name', '=', 'All / Saleable / Events')
            ], limit=1)
            for ticket in self.event_ticket_ids:
                # Create a unique product for this ticket copy via product.copy()
                # This inherits custom required fields (like doc_name) from the source product
                new_product = ticket.product_id.copy({
                    'name': f"{copy.name} - {ticket.name}",
                    'type': 'service',
                    'list_price': ticket.price,
                    'sale_ok': True,
                    'purchase_ok': False,
                    'categ_id': events_categ.id if events_categ else ticket.product_id.categ_id.id,
                })
                # Set product.product-only fields after copy
                new_product.write({
                    'lst_price': ticket.price,
                    'barcode': False,
                    'available_in_pos': True,
                })
                
                # Copy the ticket with the new product
                new_ticket = ticket.copy({
                    'event_id': copy.id,
                    'product_id': new_product.id,
                })
                _logger.info(f"Copied ticket '{ticket.name}' to event {copy.name} (price: {new_ticket.price}, product: {new_product.id})")
        
        # Generate POS barcodes for events with pay at venue enabled
        for copy in copies:
            if copy.allow_pay_at_venue and copy.has_paid_tickets:
                try:
                    copy.action_generate_pos_barcodes()
                    _logger.info(f"Generated POS barcodes for event: {copy.name}")
                except Exception as e:
                    _logger.warning(
                        "Failed to generate POS barcodes for event %s (copy of %s): %s",
                        copy.name, self.name, e
                    )
        
        if copies:
            self.write({
                'last_copied_date': fields.Date.today(),
                'copy_count': self.copy_count + len(copies),
            })
        
        return copies

    @api.model
    def _cron_generate_weekly_events(self):
        """Scheduled action to generate weekly copies for all templates"""
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        if not template_stage:
            return 0
        templates = self.search([
            ('stage_id', '=', template_stage.id),
            ('active', '=', True),
        ])
        
        total_copies = 0
        for template in templates:
            try:
                copies = template._create_weekly_copies(weeks_ahead=4)
                total_copies += len(copies)
            except Exception as e:
                _logger.error(f"Error creating copies for template {template.name}: {str(e)}")
        
        _logger.info(f"Weekly event generation completed. Created {total_copies} copies.")
        return total_copies

    def _auto_init(self):
        """Ensure custom columns exist. Safety net for failed upgrades."""
        cr = self.env.cr
        columns = [
            ('is_recurring_template', 'BOOLEAN'),
            ('recurrence_pattern', 'VARCHAR'),
            ('template_id', 'INTEGER'),
            ('last_copied_date', 'DATE'),
            ('copy_count', 'INTEGER'),
            ('allow_pay_at_venue', 'BOOLEAN'),
            ('event_fee', 'DOUBLE PRECISION'),
        ]
        for col_name, col_type in columns:
            cr.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'event_event' AND column_name = %s
            """, (col_name,))
            if not cr.fetchone():
                cr.execute(
                    "ALTER TABLE event_event ADD COLUMN {} {}".format(col_name, col_type)
                )
        super()._auto_init()

