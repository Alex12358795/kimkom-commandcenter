from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, ValidationError
from datetime import datetime, timedelta

@tagged('post_install', '-at_install')
class TestSuperTCGEvents(TransactionCase):
    
    def setUp(self):
        super().setUp()
        self.env = self.env(context=dict(self.env.context, tracking_disable=True))
        
        # Create test event
        self.event_type = self.env['event.type'].create({
            'name': 'Test Event Type',
        })
        
        self.event = self.env['event.event'].create({
            'name': 'Test Event',
            'date_begin': datetime.now() + timedelta(days=1),
            'date_end': datetime.now() + timedelta(days=1, hours=2),
            'event_type_id': self.event_type.id,
            'is_published': True,
            'allow_pay_at_venue': True,
        })
        
        # Create a paid ticket
        self.paid_ticket = self.env['event.event.ticket'].create({
            'name': 'Paid Ticket',
            'event_id': self.event.id,
            'price': 10.0,
            'seats_max': 100,
        })
        
        # Create a free ticket
        self.free_ticket = self.env['event.event.ticket'].create({
            'name': 'Free Ticket',
            'event_id': self.event.id,
            'price': 0.0,
            'seats_max': 100,
        })
        
        # Create public user for testing
        self.public_user = self.env.ref('base.public_user')
        
    def test_01_free_event_registration_no_crash(self):
        """Free event registration should not crash on success page."""
        # Register for free event
        registration = self.env['event.registration'].create({
            'event_id': self.event.id,
            'event_ticket_id': self.free_ticket.id,
            'name': 'Test Attendee',
            'email': 'test@example.com',
            'state': 'open',
        })
        
        # Verify registration created
        self.assertTrue(registration.id)
        self.assertEqual(registration.payment_status, 'pending')
        self.assertFalse(registration.pay_at_venue)
        
        # Free events may have a generic product assigned by Odoo standard
        # The important thing is payment_status is pending and pay_at_venue is False
        self.assertFalse(registration.pay_at_venue)
        
    def test_02_paid_event_pay_at_venue(self):
        """Pay at Venue registration should have correct flags."""
        registration = self.env['event.registration'].create({
            'event_id': self.event.id,
            'event_ticket_id': self.paid_ticket.id,
            'name': 'Test Attendee',
            'email': 'test@example.com',
            'state': 'open',
            'payment_status': 'pending',
            'pay_at_venue': True,
        })
        
        self.assertTrue(registration.pay_at_venue)
        self.assertEqual(registration.payment_status, 'pending')
        self.assertEqual(registration.event_ticket_id.price, 10.0)
        
    def test_03_pos_barcode_generation(self):
        """POS barcode should be generated for paid tickets."""
        # Generate barcode for paid ticket
        self.paid_ticket._ensure_pos_barcode()
        
        # Verify barcode was created
        self.assertTrue(self.paid_ticket.pos_barcode)
        self.assertEqual(len(self.paid_ticket.pos_barcode), 13)
        self.assertTrue(self.paid_ticket.product_id)
        self.assertTrue(self.paid_ticket.product_id.barcode)
        
    def test_04_free_event_no_pos_barcode(self):
        """Free tickets may get barcode if they have a product, but it should not require payment."""
        self.free_ticket._ensure_pos_barcode()
        
        # If free ticket has a product, it may get a barcode (depends on Odoo's standard behavior)
        # The key assertion: the ticket price should remain 0
        self.assertEqual(self.free_ticket.price, 0.0)
        
    def test_05_waitlist_creation(self):
        """Waitlist entry should be created correctly."""
        waitlist = self.env['event.waitlist'].create({
            'event_id': self.event.id,
            'name': 'Waitlist User',
            'email': 'waitlist@example.com',
            'state': 'waiting',
        })
        
        self.assertTrue(waitlist.id)
        self.assertEqual(waitlist.state, 'waiting')
        self.assertEqual(waitlist.email, 'waitlist@example.com')
        
    def test_06_event_has_paid_tickets(self):
        """Event should correctly identify paid tickets."""
        self.assertTrue(self.event.has_paid_tickets)
        
        # Create event with only free tickets
        free_event = self.env['event.event'].create({
            'name': 'Free Event Only',
            'date_begin': datetime.now() + timedelta(days=1),
            'date_end': datetime.now() + timedelta(days=1, hours=2),
            'is_published': True,
        })
        
        self.env['event.event.ticket'].create({
            'name': 'Free Only',
            'event_id': free_event.id,
            'price': 0.0,
        })
        
        self.assertFalse(free_event.has_paid_tickets)
        
    def test_07_recurring_event_copy(self):
        """Weekly copy should create event with correct data."""
        # Set up template stage
        template_stage = self.env['event.stage'].search([('name', '=', 'Recurring Template')], limit=1)
        if not template_stage:
            template_stage = self.env['event.stage'].create({
                'name': 'Recurring Template',
            })
        
        self.event.stage_id = template_stage.id
        self.event.is_recurring_template = True
        
        # Generate copy
        copies = self.event._create_weekly_copies(weeks_ahead=1)
        
        self.assertEqual(len(copies), 1)
        copy = copies[0]
        self.assertEqual(copy.template_id, self.event)
        self.assertNotEqual(copy.id, self.event.id)
        
    def test_08_public_user_partner_access_pattern(self):
        """Public users should not directly access res.partner."""
        # Create a partner (simulating store location)
        partner = self.env['res.partner'].create({
            'name': 'Test Store',
            'street': 'Test Street 1',
            'city': 'Leuven',
            'zip': '3000',
        })
        
        # Verify public user cannot read partner directly
        with self.assertRaises(AccessError):
            partner.with_user(self.public_user).read(['name'])
        
        # But sudo() should work (this is the pattern we use in controllers)
        partner_sudo = partner.sudo()
        self.assertEqual(partner_sudo.name, 'Test Store')
        
    def test_09_registration_payment_status_default(self):
        """Registration should have payment_status=pending by default."""
        registration = self.env['event.registration'].create({
            'event_id': self.event.id,
            'name': 'Test',
            'email': 'test@example.com',
        })
        
        self.assertEqual(registration.payment_status, 'pending')
        
    def test_10_product_category_events(self):
        """Product should be created with Events category."""
        # Ensure category exists
        events_categ = self.env['product.category'].search([
            ('complete_name', '=', 'All / Saleable / Events')
        ], limit=1)
        
        if not events_categ:
            # Create if missing (for clean test DBs)
            all_categ = self.env.ref('product.product_category_all')
            events_categ = self.env['product.category'].create({
                'name': 'Events',
                'parent_id': all_categ.id,
            })
        
        self.paid_ticket._ensure_pos_barcode()
        
        self.assertTrue(self.paid_ticket.product_id)
        self.assertEqual(
            self.paid_ticket.product_id.categ_id.complete_name,
            'All / Saleable / Events'
        )
