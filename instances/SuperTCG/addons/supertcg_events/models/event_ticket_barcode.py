from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class EventEvent(models.Model):
    _inherit = 'event.event'

    def _prepare_event_ticket_values(self, event_template_ticket):
        """Override to create a unique product for each event ticket.

        Handles custom required fields (like doc_name from atharva_theme_base)
        that may exist in the DB schema but not yet be in Odoo's _fields
        during module upgrades.
        """
        vals = super()._prepare_event_ticket_values(event_template_ticket)

        # Get the Events product category
        events_categ = self.env['product.category'].search([
            ('complete_name', '=', 'All / Saleable / Events')
        ], limit=1)

        # Get Belgian taxes: 21% sale and 21% M purchase
        sale_tax = self.env['account.tax'].search([
            ('amount', '=', 21),
            ('type_tax_use', '=', 'sale'),
        ], limit=1, order='id asc')
        purchase_tax = self.env['account.tax'].search([
            ('amount', '=', 21),
            ('type_tax_use', '=', 'purchase'),
            ('name', 'ilike', '21% M'),
        ], limit=1, order='id asc')

        # Create a new product with all known fields
        create_vals = {
            'name': f"{self.name} - {event_template_ticket.name}",
            'type': 'service',
            'list_price': event_template_ticket.price,
            'lst_price': event_template_ticket.price,
            'sale_ok': True,
            'purchase_ok': False,
            'available_in_pos': True,
            'barcode': False,
            'categ_id': events_categ.id if events_categ else self.env.ref('product.product_category_all').id,
            'taxes_id': [(6, 0, [sale_tax.id])] if sale_tax else [(6, 0, [])],
            'supplier_taxes_id': [(6, 0, [purchase_tax.id])] if purchase_tax else [(6, 0, [])],
        }

        # Handle doc_name (custom required field from atharva_theme_base).
        # During module upgrades, _fields may not yet include fields from
        # modules loaded later in the dependency graph, but the DB column
        # already exists and is NOT NULL. We use a DB default as workaround.
        self.env.cr.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'product_template' AND column_name = 'doc_name'
        """)
        doc_name_in_db = bool(self.env.cr.fetchone())
        doc_name_in_fields = 'doc_name' in self.env['product.template']._fields

        if doc_name_in_db and doc_name_in_fields:
            create_vals['doc_name'] = 'Documents'

        new_product = self._create_product_with_doc_name_fallback(create_vals)
        vals['product_id'] = new_product.id
        return vals

    def _create_product_with_doc_name_fallback(self, create_vals):
        """Create product, handling doc_name that's in DB but not in _fields."""
        self.env.cr.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'product_template' AND column_name = 'doc_name'
        """)
        doc_name_in_db = bool(self.env.cr.fetchone())
        doc_name_in_fields = 'doc_name' in self.env['product.template']._fields

        if doc_name_in_db and not doc_name_in_fields:
            # Column exists in DB but Odoo doesn't know about it yet.
            # Add a temporary DB default so PostgreSQL fills it in.
            self.env.cr.execute("""
                ALTER TABLE product_template
                ALTER COLUMN doc_name SET DEFAULT '{"en_US": "Documents"}'
            """)
            # Remove from create_vals so Odoo doesn't reject it as invalid field
            create_vals.pop('doc_name', None)
            try:
                return self.env['product.product'].create(create_vals)
            finally:
                self.env.cr.execute("""
                    ALTER TABLE product_template
                    ALTER COLUMN doc_name DROP DEFAULT
                """)
        else:
            return self.env['product.product'].create(create_vals)

    def action_generate_pos_barcodes(self):
        """Generate POS barcodes for all event tickets."""
        for event in self:
            for ticket in event.event_ticket_ids:
                try:
                    ticket._ensure_pos_barcode()
                except Exception as e:
                    _logger.warning(
                        "Could not create barcode for ticket %s (event %s): %s",
                        ticket.id, event.id, e
                    )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'POS Barcodes Generated',
                'message': f'POS barcodes generated for {len(self.event_ticket_ids)} tickets.',
                'type': 'success',
            }
        }


class EventTicket(models.Model):
    _inherit = 'event.event.ticket'

    pos_barcode = fields.Char(
        string='POS Barcode',
        help='EAN-13 barcode for POS scanning. Stored on both ticket and product.'
    )

    def _auto_init(self):
        """Ensure custom columns exist. Safety net for failed upgrades."""
        cr = self.env.cr
        cr.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'event_event_ticket' AND column_name = 'pos_barcode'
        """)
        if not cr.fetchone():
            cr.execute("ALTER TABLE event_event_ticket ADD COLUMN pos_barcode VARCHAR")
        super()._auto_init()

    @api.model
    def _calculate_ean13_checksum(self, digits12):
        """Calculate EAN-13 checksum digit for 12-digit base."""
        if len(digits12) != 12 or not digits12.isdigit():
            raise ValueError("EAN-13 base must be exactly 12 digits")

        total = 0
        for i, digit in enumerate(digits12):
            if i % 2 == 0:
                total += int(digit)
            else:
                total += int(digit) * 3

        checksum = (10 - (total % 10)) % 10
        return str(checksum)

    def _generate_ean13_barcode(self, event_id, ticket_id):
        """Generate a valid EAN-13 barcode."""
        id_combo = (event_id * 1000000 + ticket_id) % 1000000000000
        base = f"{id_combo:012d}"
        checksum = self._calculate_ean13_checksum(base)
        return base + checksum

    def _ensure_pos_barcode(self):
        """Generate barcode and store on both ticket and product."""
        self.ensure_one()

        if not self.product_id:
            return

        # Generate EAN-13 barcode
        barcode = self._generate_ean13_barcode(self.event_id.id, self.id)

        # Check collision
        existing = self.env['event.event.ticket'].search([
            ('pos_barcode', '=', barcode),
            ('id', '!=', self.id),
        ], limit=1)

        if existing:
            for seq in range(1, 10):
                alt_combo = (self.event_id.id * 1000000 + self.id + seq) % 1000000000000
                alt_barcode = f"{alt_combo:012d}"
                alt_checksum = self._calculate_ean13_checksum(alt_barcode)
                alt_barcode = alt_barcode + alt_checksum

                alt_existing = self.env['event.event.ticket'].search([
                    ('pos_barcode', '=', alt_barcode),
                    ('id', '!=', self.id),
                ], limit=1)

                if not alt_existing:
                    barcode = alt_barcode
                    break
            else:
                _logger.warning(f"Could not find unique barcode for ticket {self.id}")
                return

        # Check if product is generic
        is_generic = (
            self.product_id.id == 4 or
            (self.product_id.name == 'Event Registration' and not self.product_id.barcode)
        )

        if is_generic:
            # Try to create a unique product
            events_categ = self.env['product.category'].search([
                ('complete_name', '=', 'All / Saleable / Events')
            ], limit=1)

            sale_tax = self.env['account.tax'].search([
                ('amount', '=', 21),
                ('type_tax_use', '=', 'sale'),
            ], limit=1, order='id asc')
            purchase_tax = self.env['account.tax'].search([
                ('amount', '=', 21),
                ('type_tax_use', '=', 'purchase'),
                ('name', 'ilike', '21% M'),
            ], limit=1, order='id asc')

            create_vals = {
                'name': f"{self.event_id.name} - {self.name}",
                'type': 'service',
                'list_price': self.price,
                'lst_price': self.price,
                'sale_ok': True,
                'purchase_ok': False,
                'available_in_pos': True,
                'barcode': barcode,
                'categ_id': events_categ.id if events_categ else self.env.ref('product.product_category_all').id,
                'taxes_id': [(6, 0, [sale_tax.id])] if sale_tax else [(6, 0, [])],
                'supplier_taxes_id': [(6, 0, [purchase_tax.id])] if purchase_tax else [(6, 0, [])],
            }

            # Handle doc_name (custom required field from atharva_theme_base).
            # During module upgrades, _fields may not yet include fields from
            # modules loaded later in the dependency graph.
            self.env.cr.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'product_template' AND column_name = 'doc_name'
            """)
            doc_name_in_db = bool(self.env.cr.fetchone())
            doc_name_in_fields = 'doc_name' in self.env['product.template']._fields

            if doc_name_in_db and doc_name_in_fields:
                create_vals['doc_name'] = 'Documents'

            # Create product without savepoint. In HTTP request contexts,
            # Odoo's framework manages transactions; nested savepoints can
            # conflict (e.g., when event mail scheduler commits mid-flow).
            # Callers handle failures via try/except where needed.
            new_product = self.event_id._create_product_with_doc_name_fallback(create_vals)

            events_pos_categ = self.env['pos.category'].search([
                ('name', 'in', ['Events', 'Evenementen'])
            ], limit=1)
            if events_pos_categ:
                new_product.write({'pos_categ_ids': [(6, 0, [events_pos_categ.id])]})

            self.write({'product_id': new_product.id, 'pos_barcode': barcode})
        else:
            # Product already unique, just update barcode
            self.product_id.write({
                'barcode': barcode,
                'available_in_pos': True,
                'lst_price': self.price,
            })

            events_pos_categ = self.env['pos.category'].search([
                ('name', 'in', ['Events', 'Evenementen'])
            ], limit=1)
            if events_pos_categ:
                self.product_id.write({'pos_categ_ids': [(6, 0, [events_pos_categ.id])]})

            self.write({'pos_barcode': barcode})
