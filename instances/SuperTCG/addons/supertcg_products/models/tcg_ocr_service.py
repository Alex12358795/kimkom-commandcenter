import base64
import json
import logging
import os
import re
import requests
from odoo import models, api

logger = logging.getLogger(__name__)

HEADER_NOISE_WORDS = [
    r'\bBASIC\b', r'\bSTAGE\s*\d+\b', r'\bSTAGE\b',
    r'\bEVOLVES\b', r'\bFROM\b', r'\bINTO\b',
    r'\bLV\.?\s*\d*\b', r'\bLEVEL\b',
    r'\bHP\b', r'\bHP\s*\d+\b',
    r'\bMEGA\s+EVOLUTION\b',
]


def _clean_ocr_name(raw_text):
    cleaned = raw_text
    for pattern in HEADER_NOISE_WORDS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\b\d{2,}\b', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned

# Use absolute path for config files
ENV_FILE = '/home/extra-others/supertcg_products/.env'
GOOGLE_JSON = '/home/extra-others/supertcg_products/google-service-account.json'


def _load_env():
    logger.info('OCR: _load_env called')
    env_vars = {}
    logger.info('OCR: Checking path %s, exists=%s', ENV_FILE, os.path.exists(ENV_FILE))
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and '=' in line and not line.startswith('#'):
                    key, val = line.split('=', 1)
                    env_vars[key.strip()] = val.strip()
                    logger.info('OCR: Loaded env var: %s', key.strip())
    else:
        logger.error('OCR: ENV_FILE does not exist!')
    return env_vars


def _get_justtcg_api_key():
    logger.info('OCR: Checking for JustTCG API key at %s', ENV_FILE)
    if not os.path.exists(ENV_FILE):
        logger.error('OCR: .env file not found at %s', ENV_FILE)
        return ''
    
    env_vars = _load_env()
    key = env_vars.get('JUSTTCG_API_KEY', '')
    logger.info('OCR: JustTCG API key loaded, length=%d', len(key))
    if key:
        logger.info('OCR: JustTCG API key starts with: %s', key[:10])
    return key


def _get_google_credentials():
    logger.info('OCR: Checking for Google credentials at %s', GOOGLE_JSON)
    if not os.path.exists(GOOGLE_JSON):
        logger.error('OCR: Google JSON file NOT FOUND at %s', GOOGLE_JSON)
        return None
    try:
        with open(GOOGLE_JSON, 'r') as f:
            creds = json.load(f)
            logger.info('OCR: Google credentials loaded, project=%s', creds.get('project_id'))
            return creds
    except Exception as e:
        logger.error('OCR: Failed to load Google credentials: %s', e)
        return None


def _get_google_access_token():
    credentials = _get_google_credentials()
    if not credentials:
        logger.error('OCR: Google credentials file missing or unreadable')
        return None
    
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.service_account import Credentials
        
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        creds = Credentials.from_service_account_info(credentials, scopes=scopes)
        creds.refresh(Request())
        token = creds.token
        logger.info('OCR: Google access token obtained')
        return token
    except ImportError as e:
        logger.error('OCR: google-auth library missing on server. Error: %s', e)
        return None
    except Exception as e:
        logger.error('OCR: Failed to get Google access token: %s', e)
        return None


class TcgOcrService(models.AbstractModel):
    _name = 'tcg.ocr.service'
    _description = 'TCG OCR and Price Lookup Service'

    @api.model
    def ocr_image(self, image_base64):
        logger.info('OCR: Starting text extraction, image length=%d', len(image_base64) if image_base64 else 0)
        
        if not image_base64:
            logger.error('OCR: No image provided')
            return {'success': False, 'error': 'No image provided'}
        
        access_token = _get_google_access_token()
        if not access_token:
            logger.error('OCR: Google credentials not configured')
            return {'success': False, 'error': 'Google credentials not configured'}
        
        try:
            url = 'https://vision.googleapis.com/v1/images:annotate'
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            payload = {
                'requests': [{
                    'image': {'content': image_base64},
                    'features': [{'type': 'TEXT_DETECTION'}],
                }]
            }
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            logger.info('OCR: Google Vision API status=%d', response.status_code)
            
            if response.status_code != 200:
                logger.error('OCR: Google API error %d: %s', response.status_code, response.text[:200])
                return {'success': False, 'error': f'Google API error: {response.status_code}'}
            
            result = response.json()
            
            if 'responses' in result and result['responses']:
                annotations = result['responses'][0].get('textAnnotations', [])
                logger.info('OCR: Found %d text annotations', len(annotations))
                
                if annotations:
                    # First pass: collect ALL text with raw coordinates
                    raw_items = []  # (text, raw_x_min, raw_y_min, raw_x_max, raw_y_max)
                    
                    for ann in annotations[1:]:  # Skip first one (full text)
                        text = ann.get('description', '').strip()
                        if not text or len(text) < 1:
                            continue
                        
                        vertices = ann.get('boundingPoly', {}).get('vertices', [])
                        if not vertices:
                            vertices = ann.get('boundingPoly', {}).get('normalizedVertices', [])
                        
                        if len(vertices) >= 4:
                            xs = [v.get('x', 0) for v in vertices]
                            ys = [v.get('y', 0) for v in vertices]
                            raw_items.append((text, min(xs), min(ys), max(xs), max(ys)))
                    
                    if not raw_items:
                        if annotations[0]:
                            return {'success': True, 'text': _clean_ocr_name(annotations[0].get('description', '').strip())}
                        return {'success': True, 'text': ''}
                    
                    # Detect coordinate type and normalize to 0-1
                    max_y = max(t[4] for t in raw_items)
                    max_x = max(t[3] for t in raw_items)
                    is_normalized = max_x <= 1.0 and max_y <= 1.0
                    
                    logger.info('OCR: Coordinate type: %s (max_x=%s, max_y=%s)', 
                                'normalized' if is_normalized else 'pixel', max_x, max_y)
                    
                    # Build normalized text_items: (text, area, y_min, x_min, y_max, x_max)
                    text_items = []
                    for item in raw_items:
                        text, rx_min, ry_min, rx_max, ry_max = item
                        
                        if is_normalized:
                            nx_min, ny_min, nx_max, ny_max = rx_min, ry_min, rx_max, ry_max
                        else:
                            nx_min = rx_min / max_x if max_x > 0 else 0
                            ny_min = ry_min / max_y if max_y > 0 else 0
                            nx_max = rx_max / max_x if max_x > 0 else 0
                            ny_max = ry_max / max_y if max_y > 0 else 0
                        
                        width = nx_max - nx_min
                        height = ny_max - ny_min
                        area = width * height
                        text_items.append((text, area, ny_min, nx_min, ny_max, nx_max))
                    
                    # Log all items with normalized coords for debugging
                    text_items.sort(key=lambda x: (x[2], x[3]))
                    logger.info('OCR: All texts (normalized y_min, x_min): %s', 
                                [(t[0], round(t[2], 3), round(t[3], 3), round(t[1], 5)) for t in text_items[:10]])
                    
                    # Step 1: Find texts in the top name strip (y_max <= 12% AND x_min <= 55%)
                    name_strip = [t for t in text_items if t[4] <= 0.12 and t[3] <= 0.55]
                    
                    if name_strip:
                        # Group texts by horizontal line (same y_min within tolerance)
                        name_strip.sort(key=lambda x: (x[2], x[3]))
                        lines = []
                        for t in name_strip:
                            matched = False
                            for line in lines:
                                avg_y = sum(item[2] for item in line) / len(line)
                                if abs(t[2] - avg_y) <= 0.02:  # same horizontal line
                                    line.append(t)
                                    matched = True
                                    break
                            if not matched:
                                lines.append([t])
                        
                        # Pick the line with the largest total area
                        best_line = max(lines, key=lambda l: sum(t[1] for t in l))
                        best_line.sort(key=lambda x: x[3])  # sort left to right
                        raw_text = ' '.join([t[0] for t in best_line])
                        cleaned = _clean_ocr_name(raw_text)
                        
                        logger.info('OCR: Step1 name strip: %s', [(t[0], round(t[4], 3), round(t[3], 3)) for t in name_strip])
                        logger.info('OCR: Raw: "%s" -> Cleaned: "%s"', raw_text, cleaned)
                        return {'success': True, 'text': cleaned}
                    
                    # Step 2: Wider search - top 15%, full width
                    wider_strip = [t for t in text_items if t[4] <= 0.15]
                    if wider_strip:
                        wider_strip.sort(key=lambda x: (x[2], x[3]))
                        top_y = wider_strip[0][2]
                        top_row = [t for t in wider_strip if t[2] <= top_y + 0.03]
                        top_row.sort(key=lambda x: -x[1])
                        
                        largest_area = top_row[0][1] if top_row else 0
                        same_size = [t for t in top_row if t[1] >= largest_area * 0.80]
                        same_size.sort(key=lambda x: (x[2], x[3]))
                        raw_text = ' '.join([t[0] for t in same_size])
                        cleaned = _clean_ocr_name(raw_text)
                        
                        logger.info('OCR: Step2 wider strip: %s', [(t[0], round(t[4], 3), round(t[3], 3)) for t in wider_strip[:5]])
                        logger.info('OCR: Raw: "%s" -> Cleaned: "%s"', raw_text, cleaned)
                        return {'success': True, 'text': cleaned}
                    
                    # Step 3: Fallback - largest text anywhere in top 30%
                    top_area = [t for t in text_items if t[4] <= 0.30]
                    if top_area:
                        top_area.sort(key=lambda x: -x[1])
                        largest_area = top_area[0][1]
                        same_size = [t for t in top_area if t[1] >= largest_area * 0.80]
                        same_size.sort(key=lambda x: (x[2], x[3]))
                        raw_text = ' '.join([t[0] for t in same_size])
                        cleaned = _clean_ocr_name(raw_text)
                        return {'success': True, 'text': cleaned}
                    
                    # Step 4: Last resort - first annotation
                    if annotations[0]:
                        raw_text = annotations[0].get('description', '').strip()
                        cleaned = _clean_ocr_name(raw_text)
                        return {'success': True, 'text': cleaned}
            
            logger.warning('OCR: No text detected in image')
            return {'success': True, 'text': ''}
        except Exception as e:
            logger.error('OCR: Text extraction failed: %s', e)
            return {'success': False, 'error': str(e)}

    @api.model
    def search_card_price(self, search_term):
        # Primary: JustTCG API
        try:
            api_key = _get_justtcg_api_key()
            if not api_key:
                logger.error('OCR: JustTCG API key not configured')
                raise Exception('JustTCG API key not configured')
            
            url = 'https://api.justtcg.com/v1/cards'
            headers = {
                'X-API-Key': api_key,
            }
            params = {
                'q': search_term,
                'game': 'pokemon',
                'limit': 10,
            }
            response = requests.get(url, headers=headers, params=params, timeout=30)
            logger.info('OCR: JustTCG API status=%d', response.status_code)
            
            if response.status_code == 401:
                logger.error('OCR: JustTCG unauthorized - invalid API key')
                raise Exception('Invalid JustTCG API key')
            
            if response.status_code == 429:
                logger.error('OCR: JustTCG rate limit exceeded')
                raise Exception('Rate limit exceeded')
            
            if response.status_code != 200:
                logger.error('OCR: JustTCG API error %d: %s', response.status_code, response.text[:200])
                raise Exception(f'JustTCG error {response.status_code}')
            
            data = response.json()
            cards = data.get('data', [])
            logger.info('OCR: JUSTTCG API returning %d cards for "%s"', len(cards), search_term)
            
            # Don't raise exception - just return empty array if no cards
            if not cards:
                logger.warning('OCR: No cards found for "%s" in JustTCG', search_term)
                return {'success': True, 'cards': [], 'source': 'justtcg'}
            
            results = []
            for card in cards[:5]:
                # Get Near Mint price from variants (price is in DOLLARS, not cents!)
                price_usd = None
                variants = card.get('variants', [])
                
                # Filter to only relevant conditions (NM, LP for Pokemon)
                for variant in variants:
                    condition = variant.get('condition', '')
                    if condition in ['Near Mint', 'Lightly Played']:
                        price_usd = variant.get('price')
                        break
                
                # If no NM/LP, get first available price
                if not price_usd and variants:
                    price_usd = variants[0].get('price')
                
                # Skip cards with no valid price
                if not price_usd or price_usd <= 0:
                    continue
                
                # Price is already in USD, convert to EUR (0.92)
                price_eur = round(price_usd * 0.92, 2)
                
                # Build full variant details
                variant_details = []
                for v in variants:
                    if v.get('price', 0) > 0:
                        variant_details.append({
                            'condition': v.get('condition'),
                            'printing': v.get('printing'),
                            'price_usd': v.get('price'),
                            'price_eur': round(v.get('price') * 0.92, 2),
                        })
                
                results.append({
                    'id': card.get('id'),
                    'name': card.get('name'),
                    'set': card.get('set_name'),
                    'set_code': card.get('set'),
                    'number': card.get('number'),
                    'rarity': card.get('rarity'),
                    'tcgplayer_id': card.get('tcgplayerId'),
                    'price_eur': price_eur,
                    'price_usd': round(price_usd, 2),
                    'image_url': f"https://product-images.tcgplayer.com/{card.get('tcgplayerId')}.jpg",
                    'variants': variant_details,
                    'justtcg_id': card.get('id'),
                })
                logger.info('OCR: JustTCG card "%s" price=$%s -> €%s', card.get('name'), price_usd, price_eur)
            
            return {'success': True, 'cards': results, 'source': 'justtcg'}
        except Exception as e:
            logger.error('OCR: JustTCG failed: %s', e)
            return {'success': False, 'error': f'JustTCG API failed: {str(e)}'}