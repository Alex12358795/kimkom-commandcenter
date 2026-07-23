# HARDCODE-ISSUE-7: urllib.request was missing — CDN image download silently failed.
import urllib.request

import base64
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# NOTE: If nginx/Apache sits in front of Odoo, increase client_max_body_size
# to support large payloads (~800KB with many card images). Example:
#   client_max_body_size 10M;


class SuperTCGWebhookController(http.Controller):

    @http.route('/supertcg/webhook', type='http', auth='none', methods=['POST', 'GET'], csrf=False)
    def receive_webhook(self):
        """Public webhook endpoint for scanner batch submissions.
        
        Supports GET for Pi health checks and POST for actual payload delivery.
        Each Pi must send its unique X-API-Key. The key identifies the scanner,
        its company, and its linked IoT label printer.
        """

        # ─── GET: Health Check ───
        if request.httprequest.method == 'GET':
            _logger.debug("SuperTCG webhook: health check received.")
            return request.make_json_response(
                {'status': 'ok', 'message': 'Webhook endpoint ready'},
                status=200
            )

        # ─── API Key Verification ───
        # Each scanner device has its own unique API key.
        # The Pi must send its assigned key in the X-API-Key header.
        api_key = request.httprequest.headers.get('X-API-Key')
        matched_device = False

        if api_key:
            matched_device = request.env['supertcg.scanner.device'].sudo().search([
                ('api_key', '=', api_key),
                ('active', '=', True),
            ], limit=1)

        if not matched_device:
            _logger.warning("SuperTCG webhook called with unknown API key.")
            return request.make_json_response(
                {'error': 'Unauthorized', 'message': 'Invalid or missing X-API-Key header. Each scanner must have its own API key configured in Scanner → Devices.'},
                status=401
            )

        _logger.info("SuperTCG webhook authenticated via scanner: %s (company: %s, printer: %s)",
                     matched_device.name,
                     matched_device.company_id.name,
                     matched_device.printer_id.name if matched_device.printer_id else 'none')

        # ─── Parse JSON Body ───
        try:
            data = request.get_json_data()
        except Exception as e:
            _logger.warning("SuperTCG webhook received invalid JSON: %s", str(e))
            return request.make_json_response(
                {'error': 'Bad Request', 'message': 'Invalid JSON payload'},
                status=400
            )

        if not isinstance(data, dict):
            return request.make_json_response(
                {'error': 'Bad Request', 'message': 'Payload must be a JSON object'},
                status=400
            )

        # ─── Extract Headers ───
        batch_type = request.httprequest.headers.get('X-Batch-Type', 'inventory')
        if batch_type not in ('inventory', 'buylist'):
            batch_type = 'inventory'

        # ─── Validate Required Fields ───
        batch_id = data.get('batch_id')
        if not batch_id:
            return request.make_json_response(
                {'error': 'Bad Request', 'message': 'Missing required field: batch_id'},
                status=400
            )

        cards = data.get('cards', [])
        if not isinstance(cards, list):
            return request.make_json_response(
                {'error': 'Bad Request', 'message': 'Field "cards" must be an array'},
                status=400
            )

        # ─── Find or Create Batch ───
        existing = request.env['supertcg.batch'].sudo().search([
            ('batch_id', '=', batch_id)
        ], limit=1)

        # ─── Prepare Shared Values ───
        device_id = data.get('device_id', '')

        # Parse scanned_at — Pi sends ISO 8601 format like "2026-05-24T19:59:48"
        # Pi is in Belgium, so we convert to UTC for Odoo storage
        scanned_at = data.get('scanned_at')
        if scanned_at and isinstance(scanned_at, str):
            from datetime import datetime, timezone, timedelta

            try:
                # Handle 'Z' suffix and other ISO 8601 variants
                dt = datetime.fromisoformat(scanned_at.replace('Z', '+00:00'))
            except ValueError:
                try:
                    # Fallback for plain datetime without timezone
                    dt = datetime.strptime(scanned_at, '%Y-%m-%dT%H:%M:%S')
                except ValueError:
                    # Final fallback: use current UTC time
                    _logger.warning("SuperTCG webhook: failed to parse scanned_at '%s', using UTC now", scanned_at)
                    dt = datetime.now(timezone.utc)

            # If no timezone info, assume Pi is in Brussels (UTC+2 typically)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=2)))

            # Convert to UTC for Odoo storage
            scanned_at = dt.astimezone(timezone.utc).replace(tzinfo=None)

        # ─── Handle Existing Batch (Update Mode) ───
        if existing:
            return self._update_batch(existing, data, cards, scanned_at, device_id, matched_device)

        # ─── Create New Batch ───
        try:
            # Auto-generate a meaningful batch name
            card_count = data.get('card_count', len(cards))
            date_str = scanned_at.strftime('%d/%m/%Y') if scanned_at else ''
            auto_name = f"{matched_device.name} - {card_count} cards"
            if date_str:
                auto_name += f" - {date_str}"

            batch_vals = {
                'batch_id': batch_id,
                'batch_name': data.get('batch_name') or auto_name or batch_id,
                'batch_type': batch_type,
                'scanned_at': scanned_at,
                'device_id': device_id,
                'card_count': card_count,
                'raw_payload': data,
                'company_id': matched_device.company_id.id or request.env.company.id,
                'scanner_device_id': matched_device.id,
                'warehouse_id': matched_device.warehouse_id.id if matched_device.warehouse_id else False,
                'location_id': matched_device.location_id.id if matched_device.location_id else False,
            }

            # Auto-assign printer from device mapping (if configured)
            if matched_device.printer_id:
                batch_vals['printer_id'] = matched_device.printer_id.id
                _logger.info(
                    "SuperTCG webhook: batch %s assigned to printer '%s'",
                    batch_id, matched_device.printer_id.name
                )
            else:
                _logger.warning(
                    "SuperTCG webhook: scanner '%s' has no printer configured! Labels will fail.",
                    matched_device.name
                )

            batch = request.env['supertcg.batch'].sudo().create(batch_vals)
            _logger.info("SuperTCG webhook: created batch %s with %s cards.", batch_id, len(cards))

            # ─── Create Card Lines ───
            processed = 0
            errors = 0

            for card_data in cards:
                try:
                    self._create_card_line(batch, card_data)
                    processed += 1
                except Exception as e:
                    _logger.error(
                        "Error creating card line in batch %s: %s — Card: %s",
                        batch_id, str(e), json.dumps(card_data, default=str)[:500]
                    )
                    errors += 1

            # Update actual count — explicit browse + flush to survive ORM invalidation
            batch.env['supertcg.batch'].sudo().browse(batch.id).write({'card_count': processed})
            batch.env.cr.flush()

            # Refresh scanner device statistics
            matched_device.action_refresh_stats()

            _logger.info(
                "SuperTCG webhook: batch %s processed. Cards: %s, Errors: %s",
                batch_id, processed, errors
            )

            return request.make_json_response({
                'status': 'ok',
                'message': 'Batch received and processed',
                'batch_id': batch_id,
                'processed': processed,
                'errors': errors,
            }, status=200)

        except Exception as e:
            _logger.error("SuperTCG webhook processing error: %s", str(e), exc_info=True)
            return request.make_json_response({
                'error': 'Internal Server Error',
                'message': str(e),
            }, status=500)

    # ─── Helpers ───
    def _create_card_line(self, batch, card_data):
        """Create a single supertcg.batch.card record from Pi payload."""
        _parse_float = lambda val: float(val) if val not in (None, '', False) else 0.0
        _parse_int = lambda val: int(val) if val not in (None, '', False) else 0
        _parse_bool = lambda val: str(val).strip().lower() == 'true'

        # Map condition and detect card category from Pi payload
        CardModel = batch.env['supertcg.batch.card']
        # Pi sends condition in either 'condition' or 'remark' field
        raw_condition = str(card_data.get('condition', '') or card_data.get('remark', '') or '')
        condition = CardModel.map_condition(raw_condition)
        card_category = CardModel.detect_card_category(card_data)

        vals = {
            'batch_id': batch.id,
            'scanner_alias': str(card_data.get('scanner_alias', '') or ''),
            'sequence': _parse_int(card_data.get('seq') or card_data.get('cursor')),
            'timestamp': str(card_data.get('timestamp', '') or ''),
            'remark': raw_remark,
            'condition': condition,
            'card_category': card_category,
            'status': str(card_data.get('status', '') or ''),
            'is_error_card': _parse_bool(card_data.get('is_error_card')),
            'game_name': str(card_data.get('game_name', '') or ''),
            'card_name': str(card_data.get('card_name', '') or ''),
            'clean_name': str(card_data.get('clean_name', '') or ''),
            'card_number': str(card_data.get('card_number', '') or ''),
            'set_code': str(card_data.get('set_code', '') or ''),
            'set_name': str(card_data.get('set_name', '') or ''),
            'group_id': str(card_data.get('group_id', '') or ''),
            'category_id': str(card_data.get('category_id', '') or ''),
            'external_product_id': str(card_data.get('product_id', '') or ''),
            'handle': str(card_data.get('handle', '') or ''),
            'rarity': str(card_data.get('rarity', '') or ''),
            'published_year': _parse_int(card_data.get('published_year')),
            'printing': str(card_data.get('printing', '') or ''),
            'edition': str(card_data.get('edition', '') or ''),
            'language': str(card_data.get('language', '') or ''),
            'foil': _parse_bool(card_data.get('foil')),
            'is_reverse_holo': _parse_bool(card_data.get('is_reverse_holo')),
            'confidence': _parse_float(card_data.get('confidence')),
            'possible_mismatch': _parse_bool(card_data.get('possible_mismatch')),
            'mismatch_reason': str(card_data.get('mismatch_reason', '') or ''),
            'price_low': _parse_float(card_data.get('price_low')),
            'price_mid': _parse_float(card_data.get('price_mid')),
            'price_high': _parse_float(card_data.get('price_high')),
            'price_market': _parse_float(card_data.get('price_market')),
            'price_direct_low': _parse_float(card_data.get('price_direct_low')),
            'purchase_basis': _parse_float(card_data.get('price_low')),
            'cdn_image_url': str(card_data.get('cdn_image', '') or ''),
            'cdn_scan_image_url': str(card_data.get('cdn_scan_image', '') or ''),
            'company_id': batch.company_id.id,
        }

        # Handle product_id
        product_id_val = card_data.get('product_id', '')
        if product_id_val is not None:
            product_id_val = str(product_id_val)
        vals['external_product_id'] = product_id_val

        # Extract all ext_* fields into ext_data
        ext_data = {}
        for key, value in card_data.items():
            if str(key).startswith('ext_') and value not in (None, ''):
                ext_data[str(key)] = str(value)
        vals['ext_data'] = ext_data if ext_data else {}

        # Image — prefer base64 from payload, fallback to CDN download
        image = card_data.get('image_base64', '')
        if isinstance(image, str) and image:
            vals['image_base64'] = image
        else:
            cdn_url = card_data.get('cdn_image', '') or card_data.get('cdn_image_url', '')
            if cdn_url:
                try:
                    downloaded = self._download_image_base64(cdn_url)
                    if downloaded:
                        vals['image_base64'] = downloaded
                except Exception as img_err:
                    _logger.warning("Failed to download image from %s: %s", cdn_url, img_err)

        # HARDCODE-ISSUE-6: Pricing compute depends on batch_id.company_id which may not be
        # resolved during webhook create. Calculate directly to avoid zero pricing.
        purchase_basis = vals.get('purchase_basis') or vals.get('price_market') or 0.0
        if purchase_basis:
            try:
                config = batch.env['supertcg.pricing.config'].get_config(batch.company_id)
                if config:
                    cash_pct = config.get_purchase_pct(condition)
                    credit_pct = config.get_credit_purchase_pct(condition)
                    increment = float(config.round_to)

                    purchase = round((purchase_basis * cash_pct / 100.0) / increment) * increment
                    purchase = max(purchase, config.purchase_min_price)

                    credit = round((purchase_basis * credit_pct / 100.0) / increment) * increment
                    credit = max(credit, config.purchase_min_price)

                    market_based = round((vals.get('price_market', 0.0) * config.sales_markup_pct / 100.0) / increment) * increment
                    market_based = max(market_based, config.sales_min_price)

                    lang = str(vals.get('language', '') or '').lower()
                    is_jp = lang in ('ja', 'jp', 'japanese', 'japans')
                    floor = config.get_sales_floor(card_category, False, condition, lang)
                    sales = max(market_based, floor)

                    vals['purchase_price'] = purchase
                    vals['credit_purchase_price'] = credit
                    vals['sales_price'] = sales
            except Exception as price_err:
                _logger.warning("Failed to calculate pricing for card %s: %s", vals.get('card_name'), price_err)

        batch.env['supertcg.batch.card'].sudo().create(vals)

    def _update_batch(self, batch, data, cards, scanned_at, device_id, matched_device):
        """Update an existing batch with new/changed cards from the Pi."""
        batch_id = batch.batch_id
        _logger.info("SuperTCG webhook: updating existing batch %s with %s cards.", batch_id, len(cards))

        # Update batch metadata
        card_count = len(cards)
        date_str = scanned_at.strftime('%d/%m/%Y') if scanned_at else ''
        auto_name = f"{matched_device.name} - {card_count} cards"
        if date_str:
            auto_name += f" - {date_str}"

        batch.write({
            'batch_name': data.get('batch_name') or auto_name or batch.batch_id,
            'scanned_at': scanned_at,
            'device_id': device_id,
            'raw_payload': data,
        })

        # Build index of existing cards by external_product_id for fast lookup
        existing_cards = {
            card.external_product_id: card
            for card in batch.card_line_ids
            if card.external_product_id
        }

        created = 0
        updated = 0
        unchanged = 0
        errors = 0

        for card_data in cards:
            try:
                product_id = str(card_data.get('product_id', '') or '')
                existing_card = existing_cards.get(product_id) if product_id else None

                if existing_card:
                    changed = self._update_card_line(batch, existing_card, card_data)
                    if changed:
                        updated += 1
                    else:
                        unchanged += 1
                else:
                    self._create_card_line(batch, card_data)
                    created += 1
            except Exception as e:
                _logger.error(
                    "Error processing card in batch %s update: %s — Card: %s",
                    batch_id, str(e), json.dumps(card_data, default=str)[:500]
                )
                errors += 1

        # Recalculate totals
        batch.env['supertcg.batch'].sudo().browse(batch.id).write({
            'card_count': len(batch.card_line_ids),
        })
        batch.env.cr.flush()

        # Refresh scanner device statistics
        matched_device.action_refresh_stats()

        _logger.info(
            "SuperTCG webhook: batch %s update complete. Created: %s, Updated: %s, Unchanged: %s, Errors: %s",
            batch_id, created, updated, unchanged, errors
        )

        return request.make_json_response({
            'status': 'ok',
            'message': 'Batch updated',
            'batch_id': batch_id,
            'created': created,
            'updated': updated,
            'unchanged': unchanged,
            'errors': errors,
        }, status=200)

    def _update_card_line(self, batch, card, card_data):
        """Update an existing card line with only changed fields.

        Returns True if any field was actually changed, False otherwise.
        Never touches is_included or product_product_id — those are user-managed.
        """
        _parse_float = lambda val: float(val) if val not in (None, '', False) else 0.0
        _parse_int = lambda val: int(val) if val not in (None, '', False) else 0
        _parse_bool = lambda val: str(val).strip().lower() == 'true'

        CardModel = batch.env['supertcg.batch.card']
        # Pi sends condition in either 'condition' or 'remark' field
        raw_condition = str(card_data.get('condition', '') or card_data.get('remark', '') or '')
        new_condition = CardModel.map_condition(raw_condition)
        new_category = CardModel.detect_card_category(card_data)

        # Fields that can be updated from the Pi
        updatable_fields = {
            'scanner_alias': str(card_data.get('scanner_alias', '') or ''),
            'sequence': _parse_int(card_data.get('seq') or card_data.get('cursor')),
            'timestamp': str(card_data.get('timestamp', '') or ''),
            'remark': raw_condition,
            'condition': new_condition,
            'card_category': new_category,
            'status': str(card_data.get('status', '') or ''),
            'is_error_card': _parse_bool(card_data.get('is_error_card')),
            'game_name': str(card_data.get('game_name', '') or ''),
            'card_name': str(card_data.get('card_name', '') or ''),
            'clean_name': str(card_data.get('clean_name', '') or ''),
            'card_number': str(card_data.get('card_number', '') or ''),
            'set_code': str(card_data.get('set_code', '') or ''),
            'set_name': str(card_data.get('set_name', '') or ''),
            'group_id': str(card_data.get('group_id', '') or ''),
            'category_id': str(card_data.get('category_id', '') or ''),
            'handle': str(card_data.get('handle', '') or ''),
            'rarity': str(card_data.get('rarity', '') or ''),
            'published_year': _parse_int(card_data.get('published_year')),
            'printing': str(card_data.get('printing', '') or ''),
            'edition': str(card_data.get('edition', '') or ''),
            'language': str(card_data.get('language', '') or ''),
            'foil': _parse_bool(card_data.get('foil')),
            'is_reverse_holo': _parse_bool(card_data.get('is_reverse_holo')),
            'confidence': _parse_float(card_data.get('confidence')),
            'possible_mismatch': _parse_bool(card_data.get('possible_mismatch')),
            'mismatch_reason': str(card_data.get('mismatch_reason', '') or ''),
            'price_low': _parse_float(card_data.get('price_low')),
            'price_mid': _parse_float(card_data.get('price_mid')),
            'price_high': _parse_float(card_data.get('price_high')),
            'price_market': _parse_float(card_data.get('price_market')),
            'price_direct_low': _parse_float(card_data.get('price_direct_low')),
            'purchase_basis': _parse_float(card_data.get('price_low')),
            'cdn_image_url': str(card_data.get('cdn_image', '') or ''),
            'cdn_scan_image_url': str(card_data.get('cdn_scan_image', '') or ''),
        }

        # Check which fields actually changed
        write_vals = {}
        for field_name, new_value in updatable_fields.items():
            old_value = getattr(card, field_name, None)
            # Handle float comparison with tolerance
            if isinstance(new_value, float) and isinstance(old_value, float):
                if abs(new_value - old_value) > 0.001:
                    write_vals[field_name] = new_value
            elif new_value != old_value:
                write_vals[field_name] = new_value

        # Handle ext_data separately
        ext_data = {}
        for key, value in card_data.items():
            if str(key).startswith('ext_') and value not in (None, ''):
                ext_data[str(key)] = str(value)
        if ext_data != (card.ext_data or {}):
            write_vals['ext_data'] = ext_data

        # Handle image — only update if new image provided
        image = card_data.get('image_base64', '')
        if isinstance(image, str) and image and image != card.image_base64:
            write_vals['image_base64'] = image
        else:
            cdn_url = card_data.get('cdn_image', '') or card_data.get('cdn_image_url', '')
            if cdn_url and cdn_url != card.cdn_image_url:
                try:
                    downloaded = self._download_image_base64(cdn_url)
                    if downloaded and downloaded != card.image_base64:
                        write_vals['image_base64'] = downloaded
                        write_vals['cdn_image_url'] = cdn_url
                except Exception as img_err:
                    _logger.warning("Failed to download updated image from %s: %s", cdn_url, img_err)

        # Recalculate pricing if relevant fields changed
        pricing_fields = {'price_low', 'price_market', 'condition', 'card_category', 'language', 'purchase_basis'}
        if any(f in write_vals for f in pricing_fields):
            try:
                config = batch.env['supertcg.pricing.config'].get_config(batch.company_id)
                if config:
                    purchase_basis = write_vals.get('purchase_basis') or card.purchase_basis or card.price_low or 0.0
                    condition = write_vals.get('condition') or card.condition or 'ex'
                    category = write_vals.get('card_category') or card.card_category or 'other'
                    language = write_vals.get('language') or card.language or 'en'

                    cash_pct = config.get_purchase_pct(condition)
                    credit_pct = config.get_credit_purchase_pct(condition)
                    increment = float(config.round_to)

                    purchase = round((purchase_basis * cash_pct / 100.0) / increment) * increment
                    purchase = max(purchase, config.purchase_min_price)

                    credit = round((purchase_basis * credit_pct / 100.0) / increment) * increment
                    credit = max(credit, config.purchase_min_price)

                    market = write_vals.get('price_market') or card.price_market or 0.0
                    market_based = round((market * config.sales_markup_pct / 100.0) / increment) * increment
                    market_based = max(market_based, config.sales_min_price)

                    lang = str(language).lower()
                    is_jp = lang in ('ja', 'jp', 'japanese', 'japans')
                    # WOTC check: if set_code didn't change, use existing is_wotc
                    set_code = write_vals.get('set_code') or card.set_code
                    wotc_codes = [c.strip().upper() for c in (config.wotc_set_codes or '').split(',') if c.strip()]
                    is_wotc = bool(set_code and set_code.strip().upper() in wotc_codes)

                    floor = config.get_sales_floor(category, is_wotc, condition, lang)
                    sales = max(market_based, floor)

                    write_vals['purchase_price'] = purchase
                    write_vals['credit_purchase_price'] = credit
                    write_vals['sales_price'] = sales
            except Exception as price_err:
                _logger.warning("Failed to recalculate pricing for updated card %s: %s", card.card_name, price_err)

        if write_vals:
            card.write(write_vals)
            return True
        return False

    def _download_image_base64(self, url):
        """Download an image from URL and return as base64 string."""
        req = urllib.request.Request(url, headers={'User-Agent': 'SuperTCG-Scanner/1.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            if data:
                return base64.b64encode(data).decode('ascii')
        return False


