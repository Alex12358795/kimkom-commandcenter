def migrate(cr, version):
    """Post-migration: update event registration mail template with POS barcode section.
    
    The original template is noupdate="1", so XML data files cannot override it.
    body_html is stored as JSONB with language keys (en_US, nl_BE, etc.).
    We use raw SQL to ensure the update actually persists.
    """
    import json

    # Find the template ID
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'event' AND name = 'event_subscription'
    """)
    row = cr.fetchone()
    if not row:
        print("event.event_subscription template not found in ir_model_data, skipping")
        return

    template_id = row[0]

    # Build the POS payment section HTML (same for all languages)
    pos_section = '\n    <!-- POS PAYMENT SECTION -->\n    <tr t-if="object.pay_at_venue and object.payment_status == \'pending\' and object.event_ticket_id and object.event_ticket_id.pos_barcode">\n        <td align="center" style="min-width: 590px;">\n            <table width="590" border="0" cellpadding="0" cellspacing="0" style="min-width: 590px; background-color: #FFF3CD; padding: 16px; border-collapse:separate; border: 2px solid #FFC107; border-radius: 8px;">\n                <tr><td align="center">\n                    <span style="font-size: 14px; font-weight: bold; color: #856404; text-transform: uppercase; letter-spacing: 1px;">Betaal ter plaatse</span><br/><br/>\n                    \n                    <div style="background-color: white; padding: 15px; border-radius: 4px; display: inline-block;">\n                        <img t-attf-src="/report/barcode/EAN13/{{object.event_ticket_id.pos_barcode}}?width=250&amp;height=100&amp;quiet=0" style="max-width: 250px; height: auto; display: block; margin: 0 auto;" alt="POS Betaal Barcode"/><br/>\n                        <span style="font-size: 16px; font-weight: bold; color: #333;"><t t-out="object.event_ticket_id.pos_barcode"/></span>\n                    </div><br/><br/>\n                    \n                    <span style="font-size: 18px; font-weight: bold; color: #856404;">\n                        Te betalen: € <t t-out="object.event_ticket_id.price" t-options="{\'widget\': \'float\', \'precision\': 2}">10.00</t>\n                    </span><br/><br/>\n                    \n                    <span style="font-size: 12px; color: #856404;">\n                        Toon deze barcode aan de kassa om je betaling te voltooien.\n                    </span>\n                </td></tr>\n            </table>\n            <br/>\n        </td>\n    </tr>'

    marker = '<!-- EVENT DESCRIPTION -->'

    # Read current body_html JSONB
    cr.execute("SELECT body_html FROM mail_template WHERE id = %s", (template_id,))
    row = cr.fetchone()
    if not row or not row[0]:
        print("Template body_html is empty, skipping")
        return

    body_json = row[0]
    if isinstance(body_json, str):
        body_json = json.loads(body_json)
    elif isinstance(body_json, dict):
        pass
    else:
        print(f"Unexpected body_html type: {type(body_json)}, skipping")
        return

    updated_any = False
    for lang_key, body in body_json.items():
        if not body or 'Betaal ter plaatse' in body:
            continue
        if marker not in body:
            continue

        new_body = body.replace(marker, pos_section + '\n    ' + marker)
        body_json[lang_key] = new_body
        updated_any = True
        print(f"Updated mail template body for language: {lang_key}")

    if updated_any:
        cr.execute(
            "UPDATE mail_template SET body_html = %s WHERE id = %s",
            (json.dumps(body_json), template_id)
        )
        print("Updated event registration mail template with POS barcode section")
    else:
        print("Mail template already up to date or marker not found")

    # ------------------------------------------------------------------
    # Also fix existing products that have wrong category "All"
    # instead of "All / Saleable / Events"
    # ------------------------------------------------------------------
    cr.execute("""
        SELECT id FROM product_category WHERE complete_name = 'All / Saleable / Events'
    """)
    row = cr.fetchone()
    if row:
        events_categ_id = row[0]
        cr.execute("""
            UPDATE product_template
            SET categ_id = %s
            WHERE categ_id = (
                SELECT id FROM product_category WHERE complete_name = 'All'
            )
            AND name->>'en_US' ILIKE '%% - Registration for %%'
        """, (events_categ_id,))
        count = cr.rowcount
        if count:
            print(f"Fixed category for {count} event registration products")
    else:
        print("Category 'All / Saleable / Events' not found, skipping product fix")
