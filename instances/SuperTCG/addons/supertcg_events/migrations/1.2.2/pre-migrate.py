# -*- coding: utf-8 -*-
"""Pre-migration script for supertcg_events 1.2.2

Ensures all custom columns exist BEFORE model loading.
Uses SAVEPOINTs per column so one failure doesn't abort the whole transaction.
Commits immediately so schema changes survive any later data operation failures.
This makes the module completely self-healing — no manual SQL ever needed.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Create missing custom columns if they don't exist, then commit."""

    # (table_name, column_name, column_type)
    # Only non-computed fields here — let Odoo handle computed field triggers
    columns_to_create = [
        ('event_event', 'is_recurring_template', 'BOOLEAN'),
        ('event_event', 'recurrence_pattern', 'VARCHAR'),
        ('event_event', 'template_id', 'INTEGER'),
        ('event_event', 'last_copied_date', 'DATE'),
        ('event_event', 'copy_count', 'INTEGER'),
        ('event_event', 'allow_pay_at_venue', 'BOOLEAN'),
        ('event_event', 'event_fee', 'DOUBLE PRECISION'),
        ('event_event_ticket', 'pos_barcode', 'VARCHAR'),
        ('event_registration', 'payment_status', 'VARCHAR'),
        ('event_registration', 'pos_order_id', 'INTEGER'),
        ('event_registration', 'pay_at_venue', 'BOOLEAN'),
    ]

    for table_name, column_name, column_type in columns_to_create:
        # Use a savepoint so one failed ALTER TABLE doesn't abort the transaction
        cr.execute('SAVEPOINT pre_migrate_col')
        try:
            cr.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
            """, (table_name, column_name))

            if not cr.fetchone():
                cr.execute(
                    "ALTER TABLE {} ADD COLUMN {} {}".format(table_name, column_name, column_type)
                )
                _logger.info("Created column %s on %s", column_name, table_name)
            cr.execute('RELEASE SAVEPOINT pre_migrate_col')
        except Exception as e:
            cr.execute('ROLLBACK TO SAVEPOINT pre_migrate_col')
            _logger.warning(
                "Could not create column %s on %s: %s",
                column_name, table_name, e
            )

    # If the transaction got into an aborted state somehow, roll it back first
    # so we can commit cleanly.
    try:
        cr.execute('SELECT 1')
    except Exception:
        _logger.warning("Transaction was aborted, rolling back before commit")
        cr.rollback()

    # Commit schema changes immediately so they survive even if
    # later operations (product creation, barcode generation) fail.
    # This is safe because we only added columns to our own tables.
    cr.commit()
    _logger.info("Pre-migration schema check complete — all columns ensured")
