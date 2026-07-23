# -*- coding: utf-8 -*-
"""Post-migration script for supertcg_events 1.2.1

Generates POS barcodes for existing event tickets.
Catches ALL exceptions to ensure the upgrade completes even if product
creation fails due to custom required fields from other modules.
Uses SAVEPOINTs per ticket so one failure doesn't abort the transaction.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Generate POS barcodes for existing event tickets."""
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Wrap everything in try/except so this migration can NEVER fail the upgrade
    try:
        # Find all event tickets that don't have a barcode yet
        tickets = env['event.event.ticket'].search([
            ('pos_barcode', '=', False),
            ('price', '>', 0),
        ])

        total_tickets = 0
        failed_tickets = 0

        for ticket in tickets:
            # Use a savepoint so one ticket failure doesn't abort the transaction
            cr.execute('SAVEPOINT post_migrate_ticket')
            try:
                ticket._ensure_pos_barcode()
                total_tickets += 1
                _logger.info(
                    "Created barcode for: %s - %s -> %s",
                    ticket.event_id.name, ticket.name, ticket.pos_barcode
                )
                cr.execute('RELEASE SAVEPOINT post_migrate_ticket')
            except Exception as e:
                cr.execute('ROLLBACK TO SAVEPOINT post_migrate_ticket')
                failed_tickets += 1
                _logger.warning(
                    "Could not create barcode for ticket %s (%s - %s): %s",
                    ticket.id, ticket.event_id.name, ticket.name, e
                )

        _logger.info(
            "Post-migration complete: %s barcodes generated, %s failed",
            total_tickets, failed_tickets
        )
    except Exception as e:
        _logger.error(
            "Post-migration barcode generation completely failed: %s. "
            "Continuing upgrade anyway - barcodes can be generated later manually.",
            e
        )
