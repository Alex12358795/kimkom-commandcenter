# -*- coding: utf-8 -*-
"""Pre-migration script for supertcg_events 1.2.1

Adds missing columns that may have been lost due to previous failed upgrades.
This ensures the schema is correct before the ORM tries to access these fields.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Add missing columns that may not exist due to previous failed upgrades."""
    
    # event_event_ticket.pos_barcode - stored Char field
    cr.execute("""
        ALTER TABLE event_event_ticket
        ADD COLUMN IF NOT EXISTS pos_barcode VARCHAR
    """)
    _logger.info("Added column event_event_ticket.pos_barcode")
    
    # event_event.allow_pay_at_venue - regular Boolean field
    cr.execute("""
        ALTER TABLE event_event
        ADD COLUMN IF NOT EXISTS allow_pay_at_venue BOOLEAN DEFAULT FALSE
    """)
    _logger.info("Added column event_event.allow_pay_at_venue")
    
    # event_event.has_paid_tickets - computed stored Boolean field
    cr.execute("""
        ALTER TABLE event_event
        ADD COLUMN IF NOT EXISTS has_paid_tickets BOOLEAN DEFAULT FALSE
    """)
    _logger.info("Added column event_event.has_paid_tickets")
    
    # event_registration.pay_at_venue - regular Boolean field
    cr.execute("""
        ALTER TABLE event_registration
        ADD COLUMN IF NOT EXISTS pay_at_venue BOOLEAN DEFAULT FALSE
    """)
    _logger.info("Added column event_registration.pay_at_venue")
    
    # event_registration.reference_number - may exist from older version, drop if present
    # (This field was removed in 1.2.0 but might still exist in DB)
    cr.execute("""
        ALTER TABLE event_registration
        DROP COLUMN IF EXISTS reference_number
    """)
    _logger.info("Dropped column event_registration.reference_number if present")
    
    cr.commit()
    _logger.info("Pre-migration 1.2.1 complete: all missing columns added")
