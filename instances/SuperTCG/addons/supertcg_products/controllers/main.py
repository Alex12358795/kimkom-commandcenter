import json
import logging
import base64
import re
from datetime import date
import markupsafe

from odoo import http, _, fields
from odoo.http import request, content_disposition
from odoo.exceptions import ValidationError, AccessError, UserError

logger = logging.getLogger(__name__)


class TcgController(http.Controller):

    def _get_action_url(self, action_xml_id, record_id):
        action = request.env.ref(action_xml_id, raise_if_not_found=False)
        if action:
            return '/web#action=%d&id=%d' % (action.id, record_id)
        return False

    def _get_or_create_aankoop_product(self):
        product = request.env['product.product'].search([
            ('name', '=', 'Aankoop 2dehands'),
        ], limit=1)
        if product:
            return product
        purchase_tax = request.env['account.tax'].search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
        ], limit=1)
        template = request.env['product.template'].create({
            'name': 'Aankoop 2dehands',
            'type': 'consu',
            'purchase_ok': True,
            'sale_ok': False,
            'is_storable': False,
            'supplier_taxes_id': [(6, 0, [purchase_tax.id])] if purchase_tax else False,
        })
        product = template.product_variant_id
        logger.info('Created Aankoop 2dehands product (id=%d)', product.id)
        return product

    def _get_or_create_secondhand_journal(self):
        journal = request.env['account.journal'].search([
            ('name', '=', 'Second hand purchases'),
            ('company_id', '=', request.env.company.id),
        ], limit=1)
        if journal:
            return journal
        journal = request.env['account.journal'].create({
            'name': 'Second hand purchases',
            'code': 'SHP',
            'type': 'purchase',
            'company_id': request.env.company.id,
        })
        logger.info('Created Second hand purchases journal (id=%d)', journal.id)
        return journal

    @http.route('/tcg/hub', type='http', auth='user', website=False)
    def tcg_hub_dashboard(self, **kwargs):
        return request.render('supertcg_products.tcg_hub_dashboard', {})

    @http.route('/tcg', type='http', auth='user', website=False)
    def tcg_dashboard(self, **kwargs):
        mode = kwargs.get('mode')
        if mode == 'stock':
            return self._tcg_dashboard_with_mode('stock')
        elif mode == 'consignment':
            return self._tcg_dashboard_with_mode('consignment')
        return request.redirect('/tcg/hub')

    def _tcg_dashboard_with_mode(self, mode):
        categories = request.env['product.category'].search_read(
            [],
            ['id', 'name', 'complete_name', 'parent_id'],
            order='complete_name',
        )
        for cat in categories:
            cat['display_name'] = cat.get('complete_name', cat['name'])
        all_locs = request.env['stock.location'].search_read(
            [('usage', '=', 'internal')],
            ['id', 'name', 'complete_name'],
            order='complete_name',
        )
        locations = []
        for loc in all_locs:
            cname = loc.get('complete_name', loc['name'])
            if cname.count('/') >= 2:
                loc['display_name'] = cname
                locations.append(loc)
        group = request.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
        consignment_enabled = bool(group and group in request.env.user.groups_id)
        partner_action = request.env.ref('base.action_partner_form', raise_if_not_found=False)
        partner_action_id = partner_action.id if partner_action else 56
        return request.render('supertcg_products.tcg_dashboard', {
            'categories': categories,
            'locations': locations,
            'consignment_enabled': consignment_enabled,
            'partner_action_id': partner_action_id,
            'initial_mode': mode,
        })

    @http.route('/tcg/aankoop', type='http', auth='user', website=False)
    def tcg_aankoop_dashboard(self, **kwargs):
        partner_action = request.env.ref('base.action_partner_form', raise_if_not_found=False)
        partner_action_id = partner_action.id if partner_action else 56
        return request.render('supertcg_products.tcg_aankoop_dashboard', {
            'partner_action_id': partner_action_id,
        })

    @http.route('/tcg/cards/new', type='http', auth='user', website=False)
    def tcg_card_new(self, **kwargs):
        action = request.env.ref('supertcg_products.action_tcg_card_form', raise_if_not_found=False)
        if action:
            return request.redirect('/web#action=%d' % action.id)
        return request.redirect('/tcg')

    @http.route('/tcg/get_categories', type='json', auth='user', website=False)
    def tcg_get_categories(self, **kwargs):
        categories = request.env['product.category'].search_read(
            [],
            ['id', 'name', 'complete_name', 'parent_id'],
            order='complete_name',
        )
        for cat in categories:
            cat['display_name'] = cat.get('complete_name', cat['name'])
        return categories

    @http.route('/tcg/get_default_taxes', type='json', auth='user', website=False)
    def tcg_get_default_taxes(self, **kwargs):
        return request.env['product.product'].get_default_tcg_taxes()

    @http.route('/tcg/search_product', type='json', auth='user', website=False)
    def tcg_search_product(self, term='', **kwargs):
        results = request.env['product.product'].name_search(term, limit=20)
        return [{'id': r[0], 'name': r[1]} for r in results]

    @http.route('/tcg/get_product', type='json', auth='user', website=False)
    def tcg_get_product(self, product_id, **kwargs):
        product = request.env['product.product'].browse(int(product_id)).exists()
        if not product:
            return {'success': False, 'error': 'Product not found.'}
        taxes_id = product.taxes_id.ids if product.taxes_id else []
        supplier_taxes_id = product.supplier_taxes_id.ids if product.supplier_taxes_id else []
        quants = request.env['stock.quant'].search_read(
            [('product_id', '=', product.id), ('location_id.usage', '=', 'internal')],
            ['quantity', 'location_id'],
        )
        on_hand = sum(q['quantity'] for q in quants)
        image_url = '/web/image/product.product/%d/image_1920' % product.id if product.image_1920 else ''
        return {
            'success': True,
            'result': {
                'id': product.id,
                'name': product.name,
                'list_price': product.list_price,
                'standard_price': product.standard_price,
                'categ_id': product.categ_id.id,
                'taxes_id': taxes_id,
                'supplier_taxes_id': supplier_taxes_id,
                'on_hand_qty': on_hand,
                'barcode': product.barcode or '',
                'image_url': image_url,
            },
        }

    @http.route('/tcg/create_product', type='json', auth='user', website=False)
    def tcg_create_product(self, employee_id=None, po_id=None, **kwargs):
        try:
            employee = False
            employee_name = ''
            if employee_id:
                employee = request.env['hr.employee'].browse(int(employee_id)).exists()
                if employee:
                    employee_name = employee.name

            card_qty = float(kwargs.get('on_hand_qty', 1)) or 1.0

            result = request.env['product.product'].create_tcg_product(kwargs)
            product = request.env['product.product'].browse(result['product_id'])

            if employee_name:
                product.product_tmpl_id.message_post(
                    body=_('Card added by %s') % employee_name
                )

            if po_id:
                po = request.env['purchase.order'].browse(int(po_id)).exists()
                if po:
                    pickings = po.picking_ids.filtered(lambda p: p.state == 'done')
                    picking = pickings[:1] if pickings else False
                    if picking:
                        move_vals = {
                            'picking_id': picking.id,
                            'product_id': product.id,
                            'name': product.name,
                            'product_uom_qty': card_qty,
                            'product_uom': product.uom_id.id,
                            'location_id': picking.location_id.id,
                            'location_dest_id': picking.location_dest_id.id,
                        }
                        move = request.env['stock.move'].create(move_vals)
                        move._action_confirm()
                        move._action_assign()
                        if move.state in ('assigned', 'confirmed'):
                            move.quantity = card_qty
                            move._action_done()

                    po_line = po.order_line[:1]
                    total_qty = po_line.product_qty if po_line else 0
                    aankoop_product = self._get_or_create_aankoop_product()
                    linked_qty = sum(
                        m.product_uom_qty for m in
                        request.env['stock.move'].search([
                            ('picking_id', 'in', po.picking_ids.ids),
                            ('picking_id.state', '=', 'done'),
                            ('product_id', '!=', aankoop_product.id),
                            ('state', '=', 'done'),
                        ])
                    )
                    remaining = max(0, total_qty - linked_qty)
                    msg = _('Card "%s" x%d linked to PO by %s (%d/%d remaining)') % (
                        product.name, int(card_qty), employee_name or 'Unknown', int(remaining), int(total_qty)
                    )
                    po.message_post(body=msg)
                    result['po_name'] = po.name
                    result['po_url'] = self._get_action_url('purchase.purchase_form_action', po.id) or ''

            return {'success': True, 'result': result}
        except ValidationError as e:
            return {'success': False, 'error': str(e)}
        except AccessError:
            return {'success': False, 'error': _('Access denied. Please check your permissions.')}
        except Exception as e:
            logger.exception('Error creating TCG product')
            return {'success': False, 'error': _('An unexpected error occurred. Please try again.')}

    @http.route('/tcg/check_consignment', type='json', auth='user', website=False)
    def tcg_check_consignment(self, **kwargs):
        group = request.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
        return {'enabled': bool(group and group in request.env.user.groups_id)}

    @http.route('/tcg/get_open_purchase_orders', type='json', auth='user', website=False)
    def tcg_get_open_purchase_orders(self, **kwargs):
        results = []
        aankoop_product = self._get_or_create_aankoop_product()
        pos = request.env['purchase.order'].search(
            [('origin', 'ilike', 'Buy-in'), ('state', 'in', ('purchase', 'done'))],
            order='id desc', limit=30,
        )
        for po in pos:
            line = po.order_line[:1]
            if not line:
                continue
            total_qty = int(line.product_qty) or 0
            if total_qty <= 0:
                continue
            linked_qty = int(sum(
                m.product_uom_qty for m in
                request.env['stock.move'].search([
                    ('picking_id', 'in', po.picking_ids.ids),
                    ('picking_id.state', '=', 'done'),
                    ('product_id', '!=', aankoop_product.id),
                    ('state', '=', 'done'),
                ])
            ))
            remaining = max(0, total_qty - linked_qty)
            if remaining > 0:
                results.append({
                    'id': po.id,
                    'name': po.name,
                    'partner_name': po.partner_id.name,
                    'total_qty': total_qty,
                    'linked_qty': linked_qty,
                    'remaining_qty': remaining,
                })
        return results

    @http.route('/tcg/get_recent_additions', type='json', auth='user', website=False)
    def tcg_get_recent_additions(self, page=1, limit=20, **kwargs):
        def strip_html(html):
            return re.sub(r'<[^>]+>', '', html or '').strip()

        # -- Stock entries --
        stock_entries = {}
        messages = request.env['mail.message'].search(
            [('model', '=', 'product.template'), ('body', 'ilike', 'Card added by%')],
            order='id desc', limit=100,
        )
        for msg in messages:
            tmpl = request.env['product.template'].browse(msg.res_id).exists()
            if not tmpl:
                continue
            body = strip_html(msg.body)
            employee_name = ''
            if 'by ' in body:
                employee_name = body.split('by ')[-1].strip()
            product_product = tmpl.product_variant_id
            stock_url = ''
            if product_product:
                stock_url = '/odoo/action-product.product_template_action/%d' % tmpl.id
            key = tmpl.name.strip().lower()
            if key not in stock_entries:
                stock_entries[key] = {
                    'name': tmpl.name,
                    'employee_name': employee_name,
                    'category': tmpl.categ_id.name if tmpl.categ_id else '',
                    'price': tmpl.list_price,
                    'date': msg.create_date.isoformat() if msg.create_date else '',
                    'stock_url': stock_url,
                }

        # -- Consignment entries --
        consignment_entries = {}
        consignment_msgs = request.env['mail.message'].search(
            [('model', '=', 'stock.picking'), ('body', 'ilike', 'Consignment card%added by%')],
            order='id desc', limit=100,
        )
        for msg in consignment_msgs:
            picking = request.env['stock.picking'].browse(msg.res_id).exists()
            if not picking:
                continue
            body = strip_html(msg.body)
            employee_name = ''
            if 'by ' in body:
                employee_name = body.split('by ')[-1].strip()
            card_name = ''
            if 'card ' in body and ' added' in body:
                parts = body.split('card ')[-1]
                card_name = parts.split(' added')[0].strip()
            key = (card_name or picking.name).strip().lower()
            if key not in consignment_entries:
                consignment_entries[key] = {
                    'name': card_name or picking.name,
                    'employee_name': employee_name,
                    'partner_name': picking.partner_id.name if picking.partner_id else '',
                    'date': msg.create_date.isoformat() if msg.create_date else '',
                    'consignment_url': '/tcg/consignment',
                }

        # -- Merge by product name --
        merged = {}
        all_keys = set(stock_entries.keys()) | set(consignment_entries.keys())
        for key in all_keys:
            stock = stock_entries.get(key)
            cons = consignment_entries.get(key)
            name = stock['name'] if stock else cons['name']
            # Use most recent date
            dates = []
            if stock:
                dates.append(stock['date'])
            if cons:
                dates.append(cons['date'])
            dates.sort(reverse=True)
            merged[key] = {
                'name': name,
                'has_stock': bool(stock),
                'has_consignment': bool(cons),
                'stock_url': stock.get('stock_url', '') if stock else '',
                'consignment_url': cons.get('consignment_url', '') if cons else '',
                'employee_name': stock.get('employee_name', '') if stock else (cons.get('employee_name', '') if cons else ''),
                'category': stock.get('category', '') if stock else '',
                'price': stock.get('price', 0) if stock else 0,
                'partner_name': cons.get('partner_name', '') if cons else '',
                'date': dates[0] if dates else '',
            }

        # -- Sort by date desc and paginate --
        results = list(merged.values())
        results.sort(key=lambda x: x.get('date', ''), reverse=True)
        total = len(results)
        page = max(1, int(page))
        limit = max(1, int(limit))
        offset = (page - 1) * limit
        results = results[offset:offset + limit]
        page_count = max(1, (total + limit - 1) // limit)

        return {
            'entries': results,
            'total': total,
            'page': page,
            'page_count': page_count,
            'limit': limit,
        }

    @http.route('/tcg/create_consignment_product', type='json', auth='user', website=False)
    def tcg_create_consignment_product(self, partner_id, picking_type_id=None, employee_id=None, **kwargs):
        try:
            group = request.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
            if not group or group not in request.env.user.groups_id:
                return {'success': False, 'error': _(
                    'Consignment tracking is not enabled. Enable it in '
                    'Inventory > Settings > Consignment.'
                )}
            partner = request.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                return {'success': False, 'error': _('Partner not found.')}
            if not picking_type_id:
                picking_type = request.env['stock.picking.type'].search(
                    [('code', '=', 'incoming')], limit=1,
                )
            else:
                picking_type = request.env['stock.picking.type'].browse(int(picking_type_id)).exists()
            if not picking_type:
                return {'success': False, 'error': _('No incoming operation type found.')}

            employee = False
            employee_name = ''
            if employee_id:
                employee = request.env['hr.employee'].browse(int(employee_id)).exists()
                if employee:
                    employee_name = employee.name

            card_qty = float(kwargs.get('on_hand_qty', 1)) or 1.0
            loc_dest_id = int(kwargs.get('location_id')) if kwargs.get('location_id') else picking_type.default_location_dest_id.id
            kwargs['skip_inventory'] = True
            product_result = request.env['product.product'].create_tcg_product(kwargs)
            product = request.env['product.product'].browse(product_result['product_id'])
            picking = request.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'partner_id': partner.id,
                'owner_id': partner.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': loc_dest_id,
                'origin': 'TCG Consignment - %s' % partner.name,
            })

            request.env['stock.move'].create({
                'picking_id': picking.id,
                'product_id': product.id,
                'name': product.name,
                'product_uom_qty': card_qty,
                'product_uom': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'restrict_partner_id': partner.id,
                'price_unit': product.standard_price,
            })

            picking.action_confirm()
            if picking.state in ('confirmed', 'waiting'):
                picking.action_assign()
            for move in picking.move_ids:
                if move.state in ('confirmed', 'assigned', 'partially_available'):
                    move.quantity = move.product_uom_qty
            if picking.state in ('assigned', 'confirmed'):
                picking.button_validate()

            picking_url = self._get_action_url('stock.action_picking_tree_incoming', picking.id)
            product_result['picking_id'] = picking.id
            product_result['picking_name'] = picking.name
            product_result['picking_url'] = picking_url or ''
            product_result['consignment_mode'] = True

            product = request.env['product.product'].browse(product_result['product_id'])
            if employee_name:
                product.product_tmpl_id.message_post(
                    body=_('Consignment card added by %s') % employee_name
                )
                picking.message_post(
                    body=_('Consignment card %s added by %s') % (product.name, employee_name)
                )

            return {'success': True, 'result': product_result}

        except ValidationError as e:
            return {'success': False, 'error': str(e)}
        except AccessError:
            return {'success': False, 'error': _('Access denied. Please check your permissions.')}
        except Exception as e:
            logger.exception('Error creating consignment product')
            return {'success': False, 'error': _('Failed to create consignment product. Please try again.')}

    @http.route('/tcg/aankoop/get_picking_types', type='json', auth='user', website=False)
    def tcg_aankoop_get_picking_types(self, **kwargs):
        picking_types = request.env['stock.picking.type'].search_read(
            [('code', '=', 'incoming')],
            ['id', 'name', 'warehouse_id', 'default_location_dest_id'],
            order='name',
        )
        for pt in picking_types:
            if pt.get('warehouse_id'):
                pt['warehouse_name'] = pt['warehouse_id'][1]
            else:
                pt['warehouse_name'] = ''
        return picking_types

    @http.route('/tcg/aankoop/search_partner', type='json', auth='user', website=False)
    def tcg_aankoop_search_partner(self, term='', **kwargs):
        results = request.env['res.partner'].name_search(term, limit=20)
        return [{'id': r[0], 'name': r[1]} for r in results]

    @http.route('/tcg/aankoop/create_partner', type='json', auth='user', website=False)
    def tcg_aankoop_create_partner(self, name, **kwargs):
        partner = request.env['res.partner'].create({'name': name})
        return {'id': partner.id, 'name': partner.name}

    @http.route('/tcg/aankoop/get_employees', type='json', auth='user', website=False)
    def tcg_aankoop_get_employees(self, **kwargs):
        employees = request.env['hr.employee'].search_read(
            [],
            ['id', 'name', 'department_id'],
            order='name',
        )
        for e in employees:
            if e.get('department_id'):
                e['department_name'] = e['department_id'][1]
            else:
                e['department_name'] = ''
        return employees

    @http.route('/tcg/aankoop/get_recent_intakes', type='json', auth='user', website=False)
    def tcg_aankoop_get_recent_intakes(self, page=1, limit=20, search='', **kwargs):
        domain = [('origin', 'ilike', 'Buy-in')]
        if search:
            domain.append(('name', 'ilike', search))

        pos = request.env['purchase.order'].search(domain, order='id desc')
        total = len(pos)
        page = max(1, int(page))
        limit = max(1, int(limit))
        offset = (page - 1) * limit
        page_count = max(1, (total + limit - 1) // limit)
        pos_page = pos[offset:offset + limit]

        results = []
        for po in pos_page:
            line = po.order_line[:1]
            description = line.name if line else po.name
            employee_name = ''
            if ' - ' in (po.origin or ''):
                employee_name = po.origin.split(' - ', 1)[1]

            bill = po.invoice_ids.filtered(
                lambda m: m.move_type == 'in_invoice'
            ).sorted('id', reverse=True)[:1]

            payment_method = ''
            for msg in po.message_ids:
                body = msg.body or ''
                if 'Cash-out' in body or 'Cash (' in body:
                    payment_method = 'cash'
                    break
                elif 'Wire Transfer' in body or 'Email sent to info@supertcg.be' in body:
                    payment_method = 'wire_transfer'
                    break
                elif 'Store Credit' in body or 'eWallet Code' in body:
                    payment_method = 'store_credit'
                    break

            ewallet_code = ''
            ewallet_url = ''
            if payment_method == 'store_credit':
                ewallet_program = request.env['loyalty.program'].search(
                    [('program_type', '=', 'ewallet')], limit=1,
                )
                if ewallet_program and po.partner_id:
                    ewallet_card = request.env['loyalty.card'].search([
                        ('program_id', '=', ewallet_program.id),
                        ('partner_id', '=', po.partner_id.id),
                    ], limit=1)
                    if ewallet_card:
                        ewallet_code = ewallet_card.code
                        ewallet_url = self._get_action_url('supertcg_products.action_tcg_ewallet_cards', ewallet_card.id)

            results.append({
                'type': 'buy_in',
                'name': po.name,
                'id': po.id,
                'partner_name': po.partner_id.name,
                'employee_name': employee_name,
                'description': description,
                'amount': po.amount_total,
                'state': po.state,
                'date': po.date_order.isoformat() if po.date_order else '',
                'view_url': self._get_action_url('purchase.purchase_form_action', po.id) or '',
                'po_url': self._get_action_url('purchase.purchase_form_action', po.id) or '',
                'po_name': po.name,
                'bill_url': self._get_action_url('account.action_move_in_invoice_type', bill.id) if bill else '',
                'bill_name': bill.name if bill else '',
                'bill_print_url': '/report/pdf/account.report_invoice/%d' % bill.id if bill else '',
                'payment_method': payment_method,
                'ewallet_code': ewallet_code,
                'ewallet_url': ewallet_url,
            })

        return {
            'entries': results,
            'total': total,
            'page': page,
            'page_count': page_count,
            'limit': limit,
        }

    @http.route('/tcg/aankoop/process_buy_in', type='json', auth='user', website=False)
    def tcg_aankoop_process_buy_in(self, partner_id, picking_type_id, employee_id=None, product_qty=1.0, price_unit=0.0, payment_method='cash', description='', signature='', invoice_date_due=None, **kwargs):
        try:
            partner = request.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                return {'success': False, 'error': _('Partner not found.')}
            picking_type = request.env['stock.picking.type'].browse(int(picking_type_id)).exists()
            if not picking_type:
                return {'success': False, 'error': _('Picking type not found.')}

            employee = False
            if employee_id:
                employee = request.env['hr.employee'].browse(int(employee_id)).exists()
            if not employee:
                return {'success': False, 'error': _('Employee is required.')}
            employee_name = employee.name

            if payment_method == 'wire_transfer':
                if not partner.bank_ids:
                    return {'success': False, 'error': _('Bank account missing for wire transfer. Please add to the partner details under the accounting section.')}

            origin_parts = ['Buy-in']
            if employee_name:
                origin_parts.append(employee_name)
            origin = ' - '.join(origin_parts)

            logger.info('Buy-in started | partner=%s | method=%s | employee=%s', partner.name, payment_method, employee_name)
            po = request.env['purchase.order'].create({
                'partner_id': partner.id,
                'picking_type_id': picking_type.id,
                'origin': origin,
            })
            logger.info('PO created | name=%s', po.name)

            product = self._get_or_create_aankoop_product()

            payment_label_map = {'cash': 'Cash', 'store_credit': 'Store Credit (eWallet)', 'wire_transfer': 'Wire Transfer'}
            payment_label = payment_label_map.get(payment_method, payment_method)
            total_price = float(product_qty or 1.0) * float(price_unit or 0.0)
            line_name = '%s (by %s) - %s \u20ac%.2f' % (
                description if description else 'Aankoop 2dehands',
                employee_name,
                payment_label,
                total_price,
            )
            line_vals = {
                'order_id': po.id,
                'product_id': product.id,
                'name': line_name,
                'product_qty': float(product_qty) or 1.0,
                'price_unit': float(price_unit) or 0.0,
                'product_uom': product.uom_id.id,
            }
            purchase_tax = request.env['account.tax'].search([
                ('name', 'ilike', 'Margeinkoop'),
                ('type_tax_use', '=', 'purchase'),
            ], limit=1)
            if purchase_tax:
                line_vals['taxes_id'] = [(6, 0, [purchase_tax.id])]
            request.env['purchase.order.line'].create(line_vals)
            logger.info('PO line created | product=%s | qty=%s | price=%s', product.name, product_qty, price_unit)

            if signature:
                po.signature_data = signature
                po.message_post(
                    body=markupsafe.Markup(
                        '<p>Customer signature for buy-in %s</p>'
                        '<img src="data:image/png;base64,%s" style="max-width:400px; border:1px solid #ddd; border-radius:4px;"/>'
                    ) % (po.name, signature)
                )
                logger.info('Buy-in signature saved for PO %s', po.name)

            po.button_confirm()
            if po.state == 'to approve':
                po.button_approve()
            logger.info('PO confirmed | name=%s | state=%s', po.name, po.state)

            for picking in po.picking_ids.filtered(lambda p: p.state in ('assigned', 'confirmed')):
                for move in picking.move_ids.filtered(lambda m: m.state in ('assigned', 'confirmed', 'waiting')):
                    move.quantity = move.product_uom_qty
                picking.button_validate()
            logger.info('Picking validated | po=%s | pickings=%s', po.name, len(po.picking_ids))

            bills = po.action_create_invoice()
            bill = request.env['account.move'].browse(bills.get('res_id', False))
            if not bill or not bill.exists():
                bill = po.invoice_ids.filtered(lambda m: True).sorted('id', reverse=True)[:1]
            if not bill:
                return {'success': False, 'error': _('Failed to create vendor bill from PO.')}

            secondhand_journal = self._get_or_create_secondhand_journal()
            bill.journal_id = secondhand_journal.id
            bill.invoice_date = date.today()
            if payment_method == 'wire_transfer' and invoice_date_due:
                bill.invoice_date_due = fields.Date.to_date(invoice_date_due)
            bill.action_post()
            logger.info('Bill posted | name=%s | amount=%s', bill.name, bill.amount_residual)

            # Match bill name to PO name (after posting to avoid sequence conflicts)
            bill.name = po.name
            bill.payment_reference = po.name

            if payment_method == 'cash':
                bill.ref = 'Cash'
            elif payment_method == 'wire_transfer':
                bill.ref = 'Wire Transfer'
            elif payment_method == 'store_credit':
                bill.ref = 'Store Credit'

            result_info = {
                'po_name': po.name,
                'po_id': po.id,
                'bill_name': bill.name,
                'bill_id': bill.id,
                'amount': bill.amount_residual,
                'po_url': self._get_action_url('purchase.purchase_form_action', po.id),
                'bill_url': self._get_action_url('account.action_move_in_invoice_type', bill.id),
            }

            if payment_method == 'cash':
                cash_journal = request.env['account.journal'].search(
                    [('type', '=', 'cash'), ('company_id', '=', request.env.company.id)],
                    limit=1,
                )
                if cash_journal:
                    outbound_line = cash_journal.outbound_payment_method_line_ids[:1]
                    if outbound_line:
                        payment = request.env['account.payment'].create({
                            'payment_type': 'outbound',
                            'partner_id': partner.id,
                            'amount': bill.amount_residual,
                            'journal_id': cash_journal.id,
                            'payment_method_line_id': outbound_line.id,
                        })
                        payment.action_post()
                        payment.action_validate()

                        bill_line = bill.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable' and l.amount_residual > 0)
                        payment_line = payment.move_id.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable' and l.amount_residual < 0)
                        if bill_line and payment_line:
                            (bill_line | payment_line).reconcile()

                        result_info['payment_name'] = payment.name
                        result_info['payment_method'] = 'cash'
                        cash_out_note = _('Cash-out from POS register required: %s (ref: %s)') % (bill.amount_residual, po.name)
                        result_info['cash_out_note'] = '%s (%s)' % ('€ %.2f' % bill.amount_residual, po.name)

                        po_url = self._get_action_url('purchase.purchase_form_action', po.id) or ''
                        bill_url = self._get_action_url('account.action_move_in_invoice_type', bill.id) or ''
                        po_link = '<a href="%s" style="color: #2c6fbb; font-weight: 600;">%s</a>' % (po_url, po.name) if po_url else po.name
                        bill_link = '<a href="%s" style="color: #714B67; font-weight: 600;">%s</a>' % (bill_url, bill.name) if bill_url else bill.name
                        chatter_msg = (
                            '<div style="font-family: Arial, sans-serif; padding: 8px;">'
                            '<strong style="color: #2c6fbb; font-size: 14px;">Buy-in: %s</strong><br/><br/>'
                            '<table style="font-size: 13px; border-collapse: collapse;">'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Purchase Order</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Vendor Bill</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Operation Type</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Processed by</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Payment</td><td style="font-weight: 600;">Cash (\u20ac %.2f)</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Partner</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Payment ref</td><td style="font-weight: 600;">%s</td></tr>'
                            '</table></div>'
                        ) % (description or 'Aankoop 2dehands', po_link, bill_link, picking_type.display_name, employee_name, bill.amount_residual, partner.name, payment.name)
                        po.message_post(body=markupsafe.Markup(chatter_msg))
                        bill.message_post(body=markupsafe.Markup(chatter_msg))
                        logger.info('Cash payment settled | po=%s | bill=%s | payment=%s | amount=%s', po.name, bill.name, payment.name, bill.amount_residual)
                    else:
                        result_info['warning'] = _('No outbound payment method on Cash journal.')
                        result_info['payment_method'] = 'cash'
                        logger.warning('No outbound payment method on Cash journal | po=%s', po.name)
                else:
                    result_info['warning'] = _('No Cash journal found. Register payment manually.')
                    result_info['payment_method'] = 'cash'
                    logger.warning('No Cash journal found | po=%s', po.name)

            elif payment_method == 'wire_transfer':
                result_info['payment_method'] = 'wire_transfer'

                po_url = self._get_action_url('purchase.purchase_form_action', po.id) or ''
                bill_url = self._get_action_url('account.action_move_in_invoice_type', bill.id) or ''
                po_link = '<a href="%s" style="color: #2c6fbb; font-weight: 600;">%s</a>' % (po_url, po.name) if po_url else po.name
                bill_link = '<a href="%s" style="color: #714B67; font-weight: 600;">%s</a>' % (bill_url, bill.name) if bill_url else bill.name
                chatter_msg = (
                    '<div style="font-family: Arial, sans-serif; padding: 8px;">'
                    '<strong style="color: #607d8b; font-size: 14px;">Buy-in: %s</strong><br/><br/>'
                    '<table style="font-size: 13px; border-collapse: collapse;">'
                    '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Purchase Order</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Vendor Bill</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Operation Type</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Processed by</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Payment</td><td style="font-weight: 600;">Wire Transfer (\u20ac %.2f)</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Partner</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Status</td><td style="font-weight: 600;">Email sent to info@supertcg.be</td></tr>'
                            '</table></div>'
                        ) % (description or 'Aankoop 2dehands', po_link, bill_link, picking_type.display_name, employee_name, bill.amount_residual, partner.name)
                po.message_post(body=markupsafe.Markup(chatter_msg))
                bill.message_post(body=markupsafe.Markup(chatter_msg))

                company = request.env.company
                email_from = company.email or 'noreply@supertcg.be'
                email_body = (
                    '<div style="font-family: Arial, sans-serif; padding: 16px;">'
                    '<h2 style="color: #607d8b;">Wire Transfer Payment Required</h2>'
                    '<p style="color: #333;">A new buy-in requires a wire transfer payment. Please review the details below and process the payment via the vendor bill.</p>'
                    '<table style="font-size: 14px; border-collapse: collapse; margin-top: 12px;">'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Vendor Bill</td><td style="font-weight: 600;">%s</td></tr>'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Purchase Order</td><td style="font-weight: 600;">%s</td></tr>'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Amount</td><td style="font-weight: 600;">\u20ac %.2f</td></tr>'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Partner</td><td style="font-weight: 600;">%s</td></tr>'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Description</td><td style="font-weight: 600;">%s</td></tr>'
                    '<tr><td style="padding: 4px 16px 4px 0; color: #666;">Processed by</td><td style="font-weight: 600;">%s</td></tr>'
                    '</table>'
                    '<p style="margin-top: 20px;"><a href="%s" style="display: inline-block; padding: 12px 24px; background: #714B67; color: white; text-decoration: none; border-radius: 8px; font-weight: 600;">Open Vendor Bill</a></p>'
                    '</div>'
                ) % (bill.name, po.name, bill.amount_residual, partner.name, description or 'Aankoop 2dehands', employee_name, bill_url)
                request.env['mail.mail'].sudo().create({
                    'subject': 'Wire Transfer Payment Required: %s — %s' % (bill.name, partner.name),
                    'body_html': email_body,
                    'email_from': email_from,
                    'email_to': 'info@supertcg.be',
                }).send()
                logger.info('Wire transfer email sent | po=%s | bill=%s | recipient=info@supertcg.be', po.name, bill.name)

            elif payment_method == 'store_credit':
                ewallet_program = request.env['loyalty.program'].search(
                    [('program_type', '=', 'ewallet')], limit=1,
                )
                if not ewallet_program:
                    ewallet_program = request.env['loyalty.program'].create({
                        'name': 'Store Credit',
                        'program_type': 'ewallet',
                        'applies_on': 'future',
                    })

                card = request.env['loyalty.card'].search([
                    ('program_id', '=', ewallet_program.id),
                    ('partner_id', '=', partner.id),
                ], limit=1)
                if not card:
                    card = request.env['loyalty.card'].create({
                        'program_id': ewallet_program.id,
                        'partner_id': partner.id,
                        'points': 0,
                    })

                credit_amount = bill.amount_residual
                card.write({'points': card.points + credit_amount})

                request.env['loyalty.history'].create({
                    'card_id': card.id,
                    'description': 'TCG Buy-in credit: %s' % po.name,
                    'issued': credit_amount,
                })

                result_info['ewallet_code'] = card.code
                result_info['ewallet_balance'] = card.points
                result_info['ewallet_id'] = card.id
                result_info['ewallet_url'] = self._get_action_url('supertcg_products.action_tcg_ewallet_cards', card.id)
                result_info['payment_method'] = 'store_credit'

                po_url = self._get_action_url('purchase.purchase_form_action', po.id) or ''
                bill_url = self._get_action_url('account.action_move_in_invoice_type', bill.id) or ''
                ewallet_url = self._get_action_url('supertcg_products.action_tcg_ewallet_cards', card.id) or ''
                po_link = '<a href="%s" style="color: #2c6fbb; font-weight: 600;">%s</a>' % (po_url, po.name) if po_url else po.name
                bill_link = '<a href="%s" style="color: #714B67; font-weight: 600;">%s</a>' % (bill_url, bill.name) if bill_url else bill.name
                ewallet_link = '<a href="%s" style="color: #5b8c5a; font-weight: 600;">%s</a>' % (ewallet_url, card.code) if ewallet_url else card.code
                chatter_msg = (
                    '<div style="font-family: Arial, sans-serif; padding: 8px;">'
                    '<strong style="color: #5b8c5a; font-size: 14px;">Buy-in: %s</strong><br/><br/>'
                    '<table style="font-size: 13px; border-collapse: collapse;">'
                    '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Purchase Order</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Vendor Bill</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Operation Type</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Processed by</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Payment</td><td style="font-weight: 600;">Store Credit (\u20ac %.2f)</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">eWallet</td><td style="font-weight: 600;">%s</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">eWallet Balance</td><td style="font-weight: 600;">\u20ac %.2f</td></tr>'
                            '<tr><td style="padding: 2px 12px 2px 0; color: #666;">Partner</td><td style="font-weight: 600;">%s</td></tr>'
                            '</table></div>'
                        ) % (description or 'Aankoop 2dehands', po_link, bill_link, picking_type.display_name, employee_name, credit_amount, ewallet_link, card.points, partner.name)
                po.message_post(body=markupsafe.Markup(chatter_msg))
                bill.message_post(body=markupsafe.Markup(chatter_msg))
                logger.info('Store credit applied | po=%s | card=%s | credit=%s | balance=%s', po.name, card.code, credit_amount, card.points)

            logger.info('Buy-in complete | po=%s | method=%s | bill=%s | amount=%s', po.name, payment_method, bill.name, bill.amount_residual)
            return {
                'success': True,
                'result': result_info,
            }

        except ValidationError as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.exception('Error processing buy-in')
            return {'success': False, 'error': _('Failed to process buy-in. Please try again.')}

    @http.route('/tcg/aankoop/process_consignment', type='json', auth='user', website=False)
    def tcg_aankoop_process_consignment(self, partner_id, picking_type_id, employee_id=None, product_qty=1.0, **kwargs):
        try:
            partner = request.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                return {'success': False, 'error': _('Partner not found.')}
            picking_type = request.env['stock.picking.type'].browse(int(picking_type_id)).exists()
            if not picking_type:
                return {'success': False, 'error': _('Picking type not found.')}

            employee = False
            if employee_id:
                employee = request.env['hr.employee'].browse(int(employee_id)).exists()
            if not employee:
                return {'success': False, 'error': _('Employee is required.')}
            employee_name = employee.name

            group = request.env.ref('stock.group_tracking_owner', raise_if_not_found=False)
            if not group or group not in request.env.user.groups_id:
                return {'success': False, 'error': _(
                    'Consignment tracking is not enabled. Enable it in '
                    'Inventory > Settings > Consignment.'
                )}

            product = self._get_or_create_aankoop_product()

            loc_dest_id = int(kwargs.get('location_id')) if kwargs.get('location_id') else picking_type.default_location_dest_id.id
            picking = request.env['stock.picking'].create({
                'picking_type_id': picking_type.id,
                'partner_id': partner.id,
                'owner_id': partner.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': loc_dest_id,
                'origin': 'TCG Consignment - %s' % partner.name,
            })

            request.env['stock.move'].create({
                'picking_id': picking.id,
                'product_id': product.id,
                'name': 'Aankoop 2dehands',
                'product_uom_qty': float(product_qty) or 1.0,
                'product_uom': product.uom_id.id,
                'location_id': picking.location_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'restrict_partner_id': partner.id,
                'price_unit': product.standard_price,
            })

            picking.message_post(body=_('Consignment processed by %s') % employee_name)

            picking.action_confirm()
            if picking.state in ('confirmed', 'waiting'):
                picking.action_assign()
            for move in picking.move_ids:
                if move.state in ('confirmed', 'assigned', 'partially_available'):
                    move.quantity = move.product_uom_qty
            if picking.state in ('assigned', 'confirmed'):
                picking.button_validate()

            picking_url = self._get_action_url('stock.action_picking_tree_incoming', picking.id)

            return {
                'success': True,
                'result': {
                    'picking_name': picking.name,
                    'picking_id': picking.id,
                    'picking_state': picking.state,
                    'picking_url': picking_url,
                },
            }

        except ValidationError as e:
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.exception('Error processing consignment')
            return {'success': False, 'error': _('Failed to process consignment. Please try again.')}

    def _render_dymo_label_pdf(self, product_ids):
        products = request.env['product.product'].browse(product_ids).exists()
        template_ids = list(set(products.mapped('product_tmpl_id.id')))
        pricelist = request.env['product.pricelist'].search(
            [('company_id', '=', request.env.company.id)],
            limit=1,
        )
        wizard = request.env['product.label.layout'].create({
            'print_format': 'dymo',
            'custom_quantity': 1,
            'product_tmpl_ids': [(6, 0, template_ids)],
            'pricelist_id': pricelist.id,
        })
        xml_id, data = wizard._prepare_report_data()
        if 'quantity_by_product' in data:
            data['quantity_by_product'] = {
                str(k): v for k, v in data['quantity_by_product'].items()
            }
        report = request.env.ref(xml_id)
        pdf_content, _ = report._render_qweb_pdf(
            xml_id,
            res_ids=template_ids,
            data=data,
        )
        return pdf_content

    @http.route('/tcg/batch_print_labels', type='json', auth='user', website=False)
    def tcg_batch_print_labels(self, product_ids=None, **kwargs):
        if not product_ids:
            return {'success': False, 'error': _('No products selected.')}
        product_ids = [int(pid) for pid in product_ids]
        products = request.env['product.product'].browse(product_ids).exists()
        if not products:
            return {'success': False, 'error': _('Products not found.')}

        report_url = '/tcg/print_labels?product_ids=%s' % ','.join(str(pid) for pid in product_ids)
        return {
            'success': True,
            'report_url': report_url,
            'count': len(product_ids),
        }

    @http.route('/tcg/print_label/<int:product_id>', type='http', auth='user', website=False)
    def tcg_print_label(self, product_id, **kwargs):
        product = request.env['product.product'].browse(product_id).exists()
        if not product:
            return request.not_found()
        pdf_content = self._render_dymo_label_pdf([product_id])
        pdf_filename = 'tcg_label_%s.pdf' % (product.barcode or product_id)
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', content_disposition(pdf_filename)),
            ]
        )

    @http.route('/tcg/print_labels', type='http', auth='user', website=False)
    def tcg_print_labels(self, product_ids=None, **kwargs):
        if not product_ids:
            return request.not_found()
        product_ids = [int(i) for i in product_ids.split(',') if i.isdigit()]
        if not product_ids:
            return request.not_found()
        products = request.env['product.product'].browse(product_ids).exists()
        if not products:
            return request.not_found()
        pdf_content = self._render_dymo_label_pdf(product_ids)
        pdf_filename = 'tcg_labels_%s.pdf' % ','.join(str(pid) for pid in product_ids)
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', content_disposition(pdf_filename)),
            ]
        )

    @http.route('/tcg/consignment', type='http', auth='user', website=False)
    def tcg_consignment_dashboard(self, **kwargs):
        owners = self._get_consignment_owners()
        recent_settlements = self._get_recent_settlements()
        action = request.env.ref(
            'supertcg_products.action_tcg_consignment_settlement',
            raise_if_not_found=False,
        )
        action_id = action.id if action else 0
        stock_by_owner = request.env.ref('supertcg_products.action_tcg_consignment_stock_by_owner', raise_if_not_found=False)
        stock_by_owner_action_id = stock_by_owner.id if stock_by_owner else 0
        return request.render('supertcg_products.tcg_consignment_dashboard', {
            'owners': owners,
            'recent_settlements': recent_settlements,
            'action_id': action_id,
            'stock_by_owner_action_id': stock_by_owner_action_id,
        })

    def _get_consignment_owners(self):
        SettlementLine = request.env['tcg.consignment.settlement.line']
        owners = []

        receipt_moves = request.env['stock.move'].search([
            ('picking_id.origin', 'ilike', 'TCG Consignment'),
            ('state', '=', 'done'),
            ('restrict_partner_id', '!=', False),
        ])
        partner_products = {}
        partner_product_cost = {}
        partner_product_received_qty = {}
        for move in receipt_moves:
            pid = move.restrict_partner_id.id
            prod_id = move.product_id.id
            partner_products.setdefault(pid, set()).add(prod_id)
            partner_product_cost.setdefault(pid, {})[prod_id] = move.price_unit or move.product_id.standard_price
            partner_product_received_qty.setdefault(pid, {})[prod_id] = partner_product_received_qty.get(pid, {}).get(prod_id, 0) + move.product_uom_qty

        all_consignment_product_ids = []
        for pids in partner_products.values():
            all_consignment_product_ids.extend(pids)

        delivery_moves = request.env['stock.move'].search([
            ('product_id', 'in', all_consignment_product_ids),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
        ])
        product_delivered = {}
        for move in delivery_moves:
            product_delivered[move.product_id.id] = product_delivered.get(move.product_id.id, 0) + move.product_uom_qty

        settled_product_ids = {}
        for line in SettlementLine.search([]):
            pid = line.settlement_id.partner_id.id
            settled_product_ids.setdefault(pid, set()).add(line.product_id.id)

        for pid in partner_products:
            partner = request.env['res.partner'].browse(pid).exists()
            if not partner:
                continue
            received_products = partner_products.get(pid, set())
            settled = settled_product_ids.get(pid, set())

            in_stock = 0
            sold = 0
            total_owed = 0.0
            for product_id in received_products:
                received_qty = partner_product_received_qty.get(pid, {}).get(product_id, 0)
                delivered_qty = product_delivered.get(product_id, 0)
                sold_qty = min(received_qty, delivered_qty)
                stock_qty = received_qty - sold_qty
                if stock_qty > 0:
                    in_stock += stock_qty
                if sold_qty > 0 and product_id not in settled:
                    sold += sold_qty
                    cost = partner_product_cost.get(pid, {}).get(product_id, 0)
                    total_owed += cost * sold_qty

            initial = partner.name[0].upper() if partner.name else '?'
            summary_parts = []
            if in_stock:
                summary_parts.append('%d in stock' % in_stock)
            if sold:
                summary_parts.append('%d sold unsettled' % sold)
            if not summary_parts:
                summary_parts.append('No activity')
            owners.append({
                'id': pid,
                'name': partner.name,
                'initial': initial,
                'in_stock': in_stock,
                'sold': sold,
                'total_owed': '%.2f' % total_owed,
                'summary': ' | '.join(summary_parts),
            })
        owners.sort(key=lambda x: x['sold'], reverse=True)
        return owners

    def _get_recent_settlements(self):
        settlements = request.env['tcg.consignment.settlement'].search(
            [], order='id desc', limit=10,
        )
        results = []
        for s in settlements:
            results.append({
                'id': s.id,
                'name': s.name,
                'partner_name': s.partner_id.name,
                'amount': '%.2f' % s.total_amount,
                'state': s.state,
                'date': s.create_date.strftime('%Y-%m-%d') if s.create_date else '',
            })
        return results

    @http.route('/tcg/consignment/create_settlement', type='json', auth='user', website=False)
    def tcg_consignment_create_settlement(self, partner_id, **kwargs):
        try:
            partner = request.env['res.partner'].browse(int(partner_id)).exists()
            if not partner:
                return {'success': False, 'error': 'Partner not found.'}

            settlement = request.env['tcg.consignment.settlement'].create({
                'partner_id': partner.id,
            })
            settlement.action_fetch_sold_items()

            action = request.env.ref(
                'supertcg_products.action_tcg_consignment_settlement',
                raise_if_not_found=False,
            )
            url = '/odoo/action-%d/%d' % (action.id, settlement.id) if action else ''

            return {
                'success': True,
                'settlement_id': settlement.id,
                'settlement_name': settlement.name,
                'url': url,
            }
        except Exception as e:
            logger.exception('Error creating consignment settlement')
            return {'success': False, 'error': str(e)}

    # ============================================================
    # MARGIN ANALYSIS DASHBOARD
    # ============================================================

    @http.route('/tcg/margin', type='http', auth='user', website=False)
    def tcg_margin_dashboard(self, **kwargs):
        return request.render('supertcg_products.tcg_margin_dashboard', {})

    @http.route('/tcg/margin/get_categories', type='json', auth='user', website=False)
    def tcg_margin_get_categories(self, **kwargs):
        categories = request.env['product.category'].search_read([], ['id', 'name'], order='name')
        return categories

    @http.route('/tcg/margin/get_products', type='json', auth='user', website=False)
    def tcg_margin_get_products(self, category_id=None, cost_filter=None, price_filter=None, comp_price_filter=None, sales_filter=None, stock_filter=None, margin_filter=None, name_search=None, barcode_search=None, sort_field='margin_pct', sort_order='asc', page=1, limit=50, **kwargs):
        domain = [('barcode', '!=', False)]
        if name_search:
            domain.append(('name', 'ilike', name_search.strip()))
        if barcode_search:
            domain.append(('barcode', 'ilike', barcode_search.strip()))
        if category_id:
            if isinstance(category_id, list):
                domain.append(('categ_id', 'in', [int(c) for c in category_id]))
            else:
                domain.append(('categ_id', '=', int(category_id)))

        products = request.env['product.product'].search(domain)

        all_tax_ids = set()
        for p in products:
            all_tax_ids.update(p.taxes_id.ids)
        taxes = request.env['account.tax'].browse(list(all_tax_ids)).filtered(lambda t: t.active)
        tax_map = {t.id: t.amount for t in taxes}
        tax_name_map = {t.id: t.name for t in taxes}

        sales_data = request.env['stock.move'].read_group(
            [('picking_type_id.code', '=', 'outgoing'), ('state', '=', 'done'), ('product_id', 'in', products.ids)],
            ['product_id', 'product_uom_qty'],
            ['product_id'],
        )
        sales_map = {item['product_id'][0]: item['product_uom_qty'] for item in sales_data if item.get('product_id')}

        results = []
        for product in products:
            tax_pct = 0.0
            tax_name = ''
            is_margin = False
            for tid in product.taxes_id.ids:
                if tid in tax_map:
                    tax_pct = tax_map[tid]
                    tax_name = tax_name_map.get(tid, '')
                    is_margin = 'marge' in tax_name.lower() or 'margin' in tax_name.lower()
                    break

            if is_margin and tax_pct:
                margin_vat = ((product.list_price - product.standard_price) * tax_pct) / 100.0
                net_sales = product.list_price - margin_vat
            else:
                net_sales = product.list_price / (1 + tax_pct / 100.0) if tax_pct else product.list_price
            if product.standard_price <= 0:
                margin_pct = None
            else:
                margin_pct = ((net_sales - product.standard_price) / net_sales * 100.0) if net_sales else 0.0

            qty_available = 0
            try:
                qty_available = round(product.qty_available, 1) if product.qty_available is not None else 0
            except Exception:
                qty_available = 0

            # Calculate price diff vs CGS
            cgs_price = product.cgs_price or 0.0
            price_diff_pct = None
            if cgs_price > 0 and product.list_price > 0:
                price_diff_pct = round(((product.list_price - cgs_price) / cgs_price) * 100.0, 1)

            # Calculate price diff vs BOM
            bom_price = product.bom_price or 0.0
            bom_price_diff_pct = None
            if bom_price > 0 and product.list_price > 0:
                bom_price_diff_pct = round(((product.list_price - bom_price) / bom_price) * 100.0, 1)

            results.append({
                'id': product.id,
                'name': product.name,
                'barcode': product.barcode or '',
                'category': product.categ_id.name or '',
                'categ_id': product.categ_id.id,
                'standard_price': product.standard_price or 0.0,
                'list_price': product.list_price or 0.0,
                'tax': tax_pct,
                'tax_name': tax_name,
                'is_margin': is_margin,
                'net_sales': round(net_sales, 2),
                'margin_pct': round(margin_pct, 2) if margin_pct is not None else None,
                'sales_count': round(sales_map.get(product.id, 0), 1),
                'create_date': product.create_date.isoformat() if product.create_date else '',
                'qty_available': qty_available,
                'product_url': self._get_action_url('product.product_normal_action', product.id) or '',
                'cgs_price': cgs_price,
                'cgs_price_date': product.cgs_price_date.isoformat() if product.cgs_price_date else None,
                'bom_price': bom_price,
                'bom_price_date': product.bom_price_date.isoformat() if product.bom_price_date else None,
                'price_diff_pct': price_diff_pct,
                'bom_price_diff_pct': bom_price_diff_pct,
            })

        cost_filter = cost_filter or []
        price_filter = price_filter or []
        sales_filter = sales_filter or []
        stock_filter = stock_filter or []
        margin_filter = margin_filter or []

        def match_cost(r, f):
            if f == 'added': return r['standard_price'] > 0
            if f == 'not_added': return r['standard_price'] <= 0
            return False

        def match_price(r, f):
            if f == 'below_50': return r['list_price'] < 50
            if f == '50_100': return 50 <= r['list_price'] <= 100
            if f == 'above_100': return r['list_price'] > 100
            return False

        def match_comp_price(r, f):
            if f == 'added': return r.get('list_price', 0) > 0
            if f == 'not_added': return r.get('list_price', 0) <= 0
            return False

        def match_sales(r, f):
            if f == 'no_sales': return r['sales_count'] == 0
            if f == 'has_sales': return r['sales_count'] >= 1
            if f == '1_5': return 1 <= r['sales_count'] <= 5
            if f == '5_10': return 5 < r['sales_count'] <= 10
            if f == 'above_10': return r['sales_count'] > 10
            return False

        def match_stock(r, f):
            if f == 'no_stock': return r['qty_available'] == 0
            if f == 'has_stock': return r['qty_available'] >= 1
            if f == 'negative': return r['qty_available'] < 0
            if f == '0_5': return 1 <= r['qty_available'] <= 5
            if f == '5_10': return 5 < r['qty_available'] <= 10
            if f == 'above_10': return r['qty_available'] > 10
            return False

        def match_margin(r, f):
            if r['margin_pct'] is None: return False
            if f == 'negative': return r['margin_pct'] < 0
            if f == '0_15': return 0 <= r['margin_pct'] < 15
            if f == '15_30': return 15 <= r['margin_pct'] < 30
            if f == 'above_30': return r['margin_pct'] >= 30
            return False

        if cost_filter:
            results = [r for r in results if any(match_cost(r, f) for f in cost_filter)]
        if price_filter:
            results = [r for r in results if any(match_price(r, f) for f in price_filter)]
        if comp_price_filter:
            results = [r for r in results if any(match_comp_price(r, f) for f in comp_price_filter)]
        if sales_filter:
            results = [r for r in results if any(match_sales(r, f) for f in sales_filter)]
        if stock_filter:
            results = [r for r in results if any(match_stock(r, f) for f in stock_filter)]
        if margin_filter:
            results = [r for r in results if any(match_margin(r, f) for f in margin_filter)]

        reverse = sort_order == 'desc'

        def sort_key(item):
            val = item.get(sort_field, 0)
            if val is None:
                return float('-inf') if sort_order == 'asc' else float('inf')
            return val

        results.sort(key=sort_key, reverse=reverse)

        total = len(results)
        page = max(1, int(page))
        limit = max(1, int(limit))
        offset = (page - 1) * limit
        page_count = max(1, (total + limit - 1) // limit)
        results = results[offset:offset + limit]

        return {
            'products': results,
            'total': total,
            'page': page,
            'page_count': page_count,
        }

    @http.route('/tcg/margin/update_product', type='json', auth='user', website=False)
    def tcg_margin_update_product(self, product_id, field, value, **kwargs):
        product = request.env['product.product'].browse(int(product_id)).exists()
        if not product:
            return {'success': False, 'error': _('Product not found.')}
        if field not in ('standard_price', 'list_price'):
            return {'success': False, 'error': _('Invalid field.')}
        try:
            product.write({field: float(value)})
            return {'success': True}
        except Exception as e:
            logger.exception('Error updating product margin field')
            return {'success': False, 'error': str(e)}

    @http.route('/tcg/margin/scrape_price', type='json', auth='user', website=False, methods=['POST'])
    def tcg_margin_scrape_price(self, product_id=None, barcode=None, source='cgs', product_url=None, product_name=None, **kwargs):
        import requests

        # BOM search by name: no product_id needed, just search and return options
        if source == 'bom_search':
            if not product_name:
                return {'success': False, 'error': _('Product name is required for BOM search.')}
            try:
                n8n_webhook_url = 'http://n8n:5678/webhook/scrape-price'
                resp = requests.post(
                    n8n_webhook_url,
                    json={
                        'source': 'bom_search',
                        'product_name': product_name.strip(),
                    },
                    timeout=30,
                    headers={'Content-Type': 'application/json'},
                )
                result = resp.json()
                if result.get('success'):
                    return {'success': True, 'options': result.get('options', [])}
                else:
                    return {'success': False, 'error': result.get('error', _('Unknown error')), 'message': result.get('message', '')}
            except requests.Timeout:
                return {'success': False, 'error': _('Scraper timed out. Please try again.')}
            except Exception as e:
                logger.exception('Error searching BOM')
                return {'success': False, 'error': str(e)}

        # CGS and BOM direct URL: require product_id and barcode
        if not product_id or not barcode:
            return {'success': False, 'error': _('Product ID and barcode are required.')}

        product = request.env['product.product'].browse(int(product_id)).exists()
        if not product:
            return {'success': False, 'error': _('Product not found.')}

        try:
            n8n_webhook_url = 'http://n8n:5678/webhook/scrape-price'
            resp = requests.post(
                n8n_webhook_url,
                json={
                    'barcode': barcode.strip(),
                    'source': source,
                    'product_url': product_url.strip() if product_url else None,
                },
                timeout=30,
                headers={'Content-Type': 'application/json'},
            )
            result = resp.json()

            if result.get('success'):
                price = result.get('price')
                now = fields.Datetime.now()
                if source == 'cgs':
                    product.write({'cgs_price': price, 'cgs_price_date': now})
                elif source == 'bom':
                    product.write({'bom_price': price, 'bom_price_date': now})
                return {'success': True, 'price': price, 'source': result.get('source'), 'date': now.isoformat() if now else None}
            else:
                return {'success': False, 'error': result.get('error', _('Unknown error')), 'message': result.get('message', '')}
        except requests.Timeout:
            return {'success': False, 'error': _('Scraper timed out. Please try again.')}
        except Exception as e:
            logger.exception('Error scraping price')
            return {'success': False, 'error': str(e)}

    @http.route('/tcg/consignment/print_overview/<int:partner_id>', type='http', auth='user', website=False)
    def tcg_consignment_print_overview(self, partner_id, **kwargs):
        partner = request.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return request.not_found()

        company = request.env.company
        company_info = {
            'name': company.name or '',
            'street': company.street or '',
            'zip': company.zip or '',
            'city': company.city or '',
            'country': company.country_id.name or '',
            'vat': company.vat or '',
            'phone': company.phone or '',
            'email': company.email or '',
            'website': company.website or '',
        }

        overview = request.env['tcg.consignment.overview'].search([
            ('partner_id', '=', partner_id),
            ('in_stock_qty', '>', 0),
        ], order='category_id, product_name')

        lines = []
        total_value = 0.0
        for item in overview:
            lines.append({
                'product_name': item.product_name,
                'category': item.category_id.name if item.category_id else '',
                'received_qty': item.received_qty,
                'in_stock_qty': item.in_stock_qty,
                'location': item.location_id.complete_name if item.location_id else '',
                'cost_price': item.cost_price,
                'total_value': item.cost_price * item.in_stock_qty,
            })
            total_value += item.cost_price * item.in_stock_qty

        today = fields.Date.today().strftime('%d/%m/%Y')

        return request.render('supertcg_products.tcg_consignment_print_overview', {
            'partner': partner,
            'company': company_info,
            'lines': lines,
            'total_value': total_value,
            'today': today,
        })

    @http.route('/tcg/ocr', type='http', auth='user', website=False)
    def tcg_ocr_dashboard(self, **kwargs):
        return request.redirect('/web#action=supertcg_products.action_tcg_ocr_card_form')

    @http.route('/tcg/ocr_extract', type='json', auth='user', website=False)
    def tcg_ocr_extract(self, image, **kwargs):
        logger.info('OCR Controller: Starting OCR extraction, image length=%d', len(image) if image else 0)
        try:
            result = request.env['tcg.ocr.service'].ocr_image(image)
            logger.info('OCR Controller: OCR result success=%s', result.get('success'))
            return result
        except Exception as e:
            logger.exception('OCR Controller: OCR extraction failed')
            return {'success': False, 'error': str(e)}

    @http.route('/tcg/search_card_price', type='json', auth='user', website=False)
    def tcg_search_card_price(self, term, **kwargs):
        logger.info('OCR Controller: Price lookup for term="%s"', term)
        try:
            result = request.env['tcg.ocr.service'].search_card_price(term)
            logger.info('OCR Controller: Price lookup result success=%s, cards=%d', result.get('success'), len(result.get('cards', [])))
            return result
        except Exception as e:
            logger.exception('OCR Controller: Card price search failed')
            return {'success': False, 'error': str(e)}