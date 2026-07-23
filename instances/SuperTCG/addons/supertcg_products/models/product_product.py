import base64
import io
import logging
from PIL import Image

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

logger = logging.getLogger(__name__)

MAX_IMAGE_DIMENSION = 1920
JPEG_QUALITY = 85


def _compress_image(base64_data):
    try:
        img_data = base64.b64decode(base64_data)
        img = Image.open(io.BytesIO(img_data))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    except Exception:
        return base64_data


class ProductProduct(models.Model):
    _inherit = 'product.product'

    cgs_price = fields.Float(string='CGS Price', digits=(16, 2))
    cgs_price_date = fields.Datetime(string='CGS Price Last Updated')
    bom_price = fields.Float(string='BOM Price', digits=(16, 2))
    bom_price_date = fields.Datetime(string='BOM Price Last Updated')

    @api.model
    def create_tcg_product(self, vals):
        required_fields = ['name', 'list_price', 'standard_price', 'categ_id']
        for field in required_fields:
            if not vals.get(field):
                raise ValidationError(
                    _('%s is required.', dict(
                        name='Name', list_price='Sales Price',
                        standard_price='Cost', categ_id='Category'
                    ).get(field, field))
                )

        taxes_id = vals.pop('taxes_id', [])
        supplier_taxes_id = vals.pop('supplier_taxes_id', [])
        on_hand_qty = vals.pop('on_hand_qty', 1)
        location_id = vals.pop('location_id', None)
        skip_inventory = vals.pop('skip_inventory', False)
        photos = vals.pop('photos', [])
        main_photo = photos[0] if photos else None
        extra_photos = photos[1:] if len(photos) > 1 else []

        product_vals = {
            'name': vals['name'],
            'list_price': float(vals['list_price']),
            'standard_price': float(vals['standard_price']),
            'categ_id': int(vals['categ_id']),
            'is_storable': True,
            'sale_ok': True,
            'purchase_ok': True,
            'available_in_pos': True,
        }

        if main_photo:
            product_vals['image_1920'] = _compress_image(main_photo)

        if taxes_id:
            product_vals['taxes_id'] = [(6, 0, [int(t) for t in taxes_id])]
        if supplier_taxes_id:
            product_vals['supplier_taxes_id'] = [(6, 0, [int(t) for t in supplier_taxes_id])]

        product = self.create(product_vals)
        product.product_tmpl_id.is_published = True

        for idx, photo_b64 in enumerate(extra_photos):
            compressed = _compress_image(photo_b64)
            self.env['product.image'].create({
                'name': '%s - Image %d' % (product.name, idx + 2),
                'product_tmpl_id': product.product_tmpl_id.id,
                'image_1920': compressed,
                'sequence': 10 * (idx + 1),
            })

        if on_hand_qty and on_hand_qty > 0 and not skip_inventory:
            self._set_initial_quantity(product, on_hand_qty, location_id)

        return {
            'product_id': product.id,
            'product_name': product.name,
            'barcode': product.barcode,
            'template_id': product.product_tmpl_id.id,
        }

    @api.model
    def _set_initial_quantity(self, product, quantity, location_id=None):
        location = None
        if location_id:
            location = self.env['stock.location'].browse(int(location_id)).exists()
            if location and location.usage == 'view':
                location = self.env['stock.location'].search([
                    ('location_id', 'child_of', location.id),
                    ('usage', '=', 'internal'),
                ], limit=1)
        if not location:
            warehouse = self.env['stock.warehouse'].search(
                [('company_id', '=', self.env.company.id)], limit=1
            )
            if not warehouse:
                return
            location = warehouse.lot_stock_id
            if location.usage == 'view':
                location = self.env['stock.location'].search([
                    ('location_id', 'child_of', location.id),
                    ('usage', '=', 'internal'),
                ], limit=1)
        if not location:
            return
        self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': product.id,
            'location_id': location.id,
            'inventory_quantity': float(quantity),
        })._apply_inventory()

    @api.model
    def get_default_tcg_taxes(self):
        sale_tax = self.env['account.tax'].search([
            ('name', 'ilike', 'Margeverkoop'),
            ('type_tax_use', '=', 'sale'),
        ], limit=1)
        purchase_tax = self.env['account.tax'].search([
            ('name', 'ilike', 'Margeinkoop'),
            ('type_tax_use', '=', 'purchase'),
        ], limit=1)
        result = {
            'sale_tax_id': sale_tax.id if sale_tax else False,
            'sale_tax_name': sale_tax.name if sale_tax else False,
            'purchase_tax_id': purchase_tax.id if purchase_tax else False,
            'purchase_tax_name': purchase_tax.name if purchase_tax else False,
        }
        result['sale_tax_found'] = bool(sale_tax)
        result['purchase_tax_found'] = bool(purchase_tax)
        return result
