from . import models
from . import controllers

def post_init_hook(env):
    """Post-init hook to generate POS barcodes and update mail template."""
    
    # Generate barcodes for all paid tickets that don't have one yet
    tickets = env['event.event.ticket'].search([
        ('pos_barcode', '=', False),
        ('price', '>', 0),
    ])
    
    total_tickets = 0
    for ticket in tickets:
        try:
            ticket._ensure_pos_barcode()
            total_tickets += 1
        except Exception as e:
            _logger.warning(f"Could not create barcode for ticket {ticket.id}: {e}")
    
    # Force-update the event registration mail template
    # (Original template is noupdate="1", so XML override won't work on update)
    _update_event_mail_template(env)
    
    env.cr.commit()
    print(f"Regenerated POS barcodes for {total_tickets} tickets")

def _update_event_mail_template(env):
    """Force-update the event registration confirmation email template.
    
    The original event.event_subscription template is marked noupdate="1",
    so our XML data file cannot override it during module update.
    This function programmatically injects the POS payment section.
    """
    template = env.ref('event.event_subscription', raise_if_not_found=False)
    if not template:
        return
    
    # Build the POS payment section HTML
    pos_section = '''
    <!-- POS PAYMENT SECTION -->
    <tr t-if="object.pay_at_venue and object.payment_status == 'pending' and object.event_ticket_id and object.event_ticket_id.pos_barcode">
        <td align="center" style="min-width: 590px;">
            <table width="590" border="0" cellpadding="0" cellspacing="0" style="min-width: 590px; background-color: #FFF3CD; padding: 16px; border-collapse:separate; border: 2px solid #FFC107; border-radius: 8px;">
                <tr><td align="center">
                    <span style="font-size: 14px; font-weight: bold; color: #856404; text-transform: uppercase; letter-spacing: 1px;">Betaal ter plaatse</span><br/><br/>
                    
                    <div style="background-color: white; padding: 15px; border-radius: 4px; display: inline-block;">
                        <img t-attf-src="/report/barcode/EAN13/{{object.event_ticket_id.pos_barcode}}?width=250&amp;height=100&amp;quiet=0" style="max-width: 250px; height: auto; display: block; margin: 0 auto;" alt="POS Betaal Barcode"/><br/>
                        <span style="font-size: 16px; font-weight: bold; color: #333;"><t t-out="object.event_ticket_id.pos_barcode"/></span>
                    </div><br/><br/>
                    
                    <span style="font-size: 18px; font-weight: bold; color: #856404;">
                        Te betalen: € <t t-out="object.event_ticket_id.price" t-options="{'widget': 'float', 'precision': 2}">10.00</t>
                    </span><br/><br/>
                    
                    <span style="font-size: 12px; color: #856404;">
                        Toon deze barcode aan de kassa om je betaling te voltooien.
                    </span>
                </td></tr>
            </table>
            <br/>
        </td>
    </tr>
    '''
    
    # Insert POS section before the EVENT DESCRIPTION comment
    marker = '<!-- EVENT DESCRIPTION -->'
    
    # Update all language translations of the template
    # body_html is a translated field stored as JSONB with language keys
    languages = env['res.lang'].search([('active', '=', True)]).mapped('code')
    languages.append(False)  # Also update the raw/untranslated version
    
    updated = False
    for lang in languages:
        ctx = {'lang': lang} if lang else {}
        template_with_lang = template.with_context(**ctx)
        body = template_with_lang.body_html
        
        if not body or 'Betaal ter plaatse' in body:
            continue
        
        if marker in body:
            new_body = body.replace(marker, pos_section + '\n    ' + marker)
            template_with_lang.write({'body_html': new_body})
            updated = True
            print(f"Updated mail template for language: {lang or 'default'}")
    
    if updated:
        print("Updated event registration mail template with POS barcode section")
    else:
        print("Mail template already up to date or marker not found")
