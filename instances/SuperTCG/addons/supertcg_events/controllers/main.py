from odoo import http, _
from odoo.http import request
from odoo.addons.website_event.controllers.main import WebsiteEventController
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import werkzeug
import logging

_logger = logging.getLogger(__name__)

class SuperTCGEventController(WebsiteEventController):

    @http.route('/events/locations', type='http', auth='public', website=True)
    def events_locations(self, **kwargs):
        """Landing page showing all store locations with events.

        We extract plain values from res.partner instead of passing recordsets
        to the template, because public users don't have read access to
        res.partner records that aren't their own commercial partner.
        """

        # Get all unique locations that have upcoming published events
        today = datetime.now()
        four_weeks_later = today + timedelta(weeks=4)

        # Search for events in the next 4 weeks
        # Public users have read access to published events via standard ACLs
        events = request.env['event.event'].search([
            ('is_published', '=', True),
            ('date_begin', '>=', today),
            ('date_begin', '<=', four_weeks_later),
        ])

        # Collect partner IDs from events so we can read them with sudo()
        partner_ids = set()
        for event in events:
            if event.address_id:
                partner_ids.add(event.address_id.id)

        # Read partner data with sudo() — store locations are public info.
        # We build a lookup dict and pass plain values to the template.
        partners = {}
        if partner_ids:
            for partner in request.env['res.partner'].sudo().browse(list(partner_ids)):
                partners[partner.id] = {
                    'name': partner.name or '',
                    'slug': request.env['ir.http']._slug(partner),
                    'street': partner.street or '',
                    'zip': partner.zip or '',
                    'city': partner.city or '',
                }

        # Group events by location — extract plain values, never pass
        # res.partner recordsets to the template (public users can't read them)
        locations = {}
        for event in events:
            location_key = event.address_id.id if event.address_id else 'online'
            location_name = 'Online'

            if location_key != 'online' and location_key in partners:
                location_name = partners[location_key]['name']
                address_slug = partners[location_key]['slug']
                address_street = partners[location_key]['street']
                address_zip = partners[location_key]['zip']
                address_city = partners[location_key]['city']
            else:
                address_slug = 'online'
                address_street = ''
                address_zip = ''
                address_city = ''

            if location_key not in locations:
                locations[location_key] = {
                    'name': location_name,
                    'address_slug': address_slug,
                    'address_street': address_street,
                    'address_zip': address_zip,
                    'address_city': address_city,
                    'events': [],
                    'event_count': 0,
                }

            locations[location_key]['events'].append(event)
            locations[location_key]['event_count'] += 1

        # Store location images (you can customize these)
        location_images = {
            # Leuven 122
            13: '/web/image/res.partner/13/image_1920',
            # Leuven 49
            14: '/web/image/res.partner/14/image_1920',
            # Mechelen
            7262: '/web/image/res.partner/7262/image_1920',
            # Hasselt
            8310: '/web/image/res.partner/8310/image_1920',
        }

        return request.render('supertcg_events.events_locations_page', {
            'locations': locations,
            'location_images': location_images,
        })

    @http.route('/events/location/<string:location_identifier>', type='http', auth='public', website=True)
    def events_by_location(self, location_identifier, **kwargs):
        """Show events for a specific location (accepts both ID and slug).

        We read res.partner fields with sudo() and pass a plain dict to the
        template, because public users don't have read access to res.partner
        records that aren't their own commercial partner.
        """

        # Try to parse as integer first
        if location_identifier.isdigit():
            location_id = int(location_identifier)
        else:
            # Extract ID from slug (e.g., "supertcg-mechelen-7262" -> 7262)
            parts = location_identifier.split('-')
            for part in reversed(parts):
                if part.isdigit():
                    location_id = int(part)
                    break
            else:
                return request.not_found()

        # Use sudo() to read the partner — store locations are public info.
        # We immediately extract plain values and never pass the recordset.
        partner = request.env['res.partner'].sudo().browse(location_id)
        if not partner.exists():
            return request.not_found()

        location = {
            'id': partner.id,
            'name': partner.name or '',
            'street': partner.street or '',
            'zip': partner.zip or '',
            'city': partner.city or '',
        }

        today = datetime.now()

        events = request.env['event.event'].search([
            ('is_published', '=', True),
            ('address_id', '=', partner.id),
            ('date_begin', '>=', today),
        ], order='date_begin asc')

        # Explicitly read image_1024 to ensure it's loaded in the template
        events.read(['image_1024'])

        return request.render('supertcg_events.events_by_location_page', {
            'location': location,
            'events': events,
        })

    @http.route('/event/<string:event_slug>/waitlist', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def event_waitlist_submit(self, event_slug, **post):
        """Handle waitlist form submission for sold-out events"""
        
        # Validate event_slug to prevent injection
        if not event_slug or len(event_slug) > 200:
            return request.not_found()
        
        # Sanitize slug for use in redirects (prevent open redirect)
        safe_slug = werkzeug.utils.secure_filename(event_slug)
        
        # Extract event ID from slug (Odoo slugs are typically "event-name-id" format)
        parts = event_slug.split('-')
        event_id = None
        for part in reversed(parts):
            if part.isdigit():
                event_id = int(part)
                break
        
        if event_id:
            event = request.env['event.event'].browse(event_id)
        else:
            # Fallback: search by name
            event = request.env['event.event'].search([
                ('website_published', '=', True),
                ('name', 'ilike', event_slug.replace('-', ' '))
            ], limit=1)
        
        if not event or not event.exists():
            return request.not_found()
        
        # Check if event is actually sold out
        if not event.event_registrations_sold_out:
            return request.redirect('/event/%s' % werkzeug.utils.secure_filename(event_slug))
        
        # Get form data
        name = post.get('waitlist_name', '').strip()
        email = post.get('waitlist_email', '').strip().lower()
        phone = post.get('waitlist_phone', '').strip()
        
        # Validate
        if not name or not email:
            return request.redirect('/event/%s/register?waitlist_error_missing_fields=1' % safe_slug)
        
        if '@' not in email:
            return request.redirect('/event/%s/register?waitlist_error_invalid_email=1' % safe_slug)
        
        try:
            # Check if already on waitlist
            # sudo() needed: public users don't have read access to other waitlist entries
            existing = request.env['event.waitlist'].sudo().search([
                ('event_id', '=', event.id),
                ('email', '=', email),
                ('state', 'in', ['waiting', 'notified'])
            ], limit=1)
            
            if existing:
                return request.redirect('/event/%s/register?waitlist_error_already_registered=1' % safe_slug)
            
            # Create waitlist entry
            # sudo() needed: public users have create access but may need elevated context
            request.env['event.waitlist'].sudo().create({
                'event_id': event.id,
                'name': name,
                'email': email,
                'phone': phone,
                'state': 'waiting',
            })
            
            return request.redirect('/event/%s/register?waitlist_success=1' % safe_slug)
            
        except ValidationError as e:
            # Known validation error (e.g., invalid email, duplicate)
            _logger.warning(_("Waitlist validation error for event %s: %s"), event.id, e)
            return request.redirect('/event/%s/register?waitlist_error_validation=1' % safe_slug)
        except Exception as e:
            # Unexpected error - log it for debugging
            _logger.error(_("Unexpected waitlist error for event %s: %s"), event.id, e, exc_info=True)
            return request.redirect('/event/%s/register?waitlist_error_unknown=1' % safe_slug)

    @http.route(['/event/<model("event.event"):event>/registration/confirm-pay-at-venue'], type='http', auth="public", methods=['POST'], website=True)
    def registration_confirm_pay_at_venue(self, event, **post):
        """Handle registration with Pay at Venue option.
        
        This creates a registration with pending payment status and generates
        a reference number for venue payment matching.
        """
        if not event.allow_pay_at_venue or not event.has_paid_tickets:
            return request.redirect('/event/%s/register' % event.id)
        
        # Process the standard attendees form to extract registration data
        registrations_data = self._process_attendees_form(event, post)
        
        if not registrations_data:
            return request.redirect('/event/%s/register?registration_error_code=invalid_form' % event.id)
        
        try:
            # For Pay at Venue, we only support single attendee registration
            registration_data = registrations_data[0]
            
            # Get ticket price
            ticket_id = registration_data.get('event_ticket_id', False)
            ticket = request.env['event.event.ticket'].browse(ticket_id) if ticket_id else None
            ticket_price = ticket.price if ticket and ticket.exists() else 0
            
            # Create registration with Pay at Venue
            # Odoo's web framework already handles transaction isolation.
            # If create() fails, the request transaction is rolled back automatically.
            registration = request.env['event.registration'].create({
                'event_id': event.id,
                'event_ticket_id': ticket_id,
                'name': registration_data.get('name', ''),
                'email': registration_data.get('email', ''),
                'phone': registration_data.get('phone', ''),
                'state': 'open',  # Reserve seat immediately
                'payment_status': 'pending',
                'pay_at_venue': True,
            })
            
            # Redirect to confirmation page with reference
            return request.redirect('/event/%s/registration/success?%s' % (
                event.id,
                werkzeug.urls.url_encode({
                    'registration_ids': str(registration.id),
                    'pay_at_venue': '1',
                    'fee': str(ticket_price),
                })
            ))
            
        except ValidationError as e:
            # Known validation error (e.g., event full, invalid data)
            _logger.warning(_("Pay at venue validation error for event %s: %s"), event.id, e)
            return request.redirect('/event/%s/register?error=validation' % event.id)
        except Exception as e:
            # Unexpected error - log full traceback for debugging
            _logger.exception(_("Pay at venue registration failed for event %s"), event.id)
            return request.redirect('/event/%s/register?error=%s' % (event.id, type(e).__name__))
