from odoo import api, SUPERUSER_ID

def regenerate_pos_barcodes(env):
    """Post-init hook to regenerate POS barcodes for existing events.
    
    This ensures all existing events with paid tickets get proper
    unique products with barcodes.
    """
    # Find events with paid tickets
    events = env['event.event'].search([
        ('event_ticket_ids.price', '>', 0),
    ])
    
    total_tickets = 0
    for event in events:
        for ticket in event.event_ticket_ids:
            if ticket.price > 0:
                # Check if ticket uses generic product
                if ticket.product_id and ticket.product_id.name == 'Event Registration':
                    try:
                        # Create new product for this ticket
                        ticket._ensure_pos_barcode()
                        total_tickets += 1
                    except Exception as e:
                        import logging
                        _logger = logging.getLogger(__name__)
                        _logger.warning("Could not create barcode for ticket %s: %s", ticket.id, e)
    
    env.cr.commit()
    return total_tickets
