from odoo import api, fields, models, _


class SuperTCGScannerDevice(models.Model):
    _name = 'supertcg.scanner.device'
    _description = 'Scanner Device Configuration'
    _order = 'name'

    name = fields.Char(
        string='Device Name',
        required=True,
        help='e.g., "Hasselt Store Scanner"',
    )
    api_key = fields.Char(
        string='Scanner API Key',
        required=True,
        help='Unique API key for this scanner. The Pi must send this key in the X-API-Key header.',
        copy=False,
    )
    pi_url = fields.Char(
        string='Pi URL',
        default='https://supertcg-pi.bore.digital/api/batches',
        help='URL of the Pi status server endpoint for pulling batches (e.g., https://supertcg-pi.bore.digital/api/batches)',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Store',
        required=True,
        default=lambda self: self.env.company,
        help='Which store this scanner belongs to',
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        check_company=True,
        help='Default warehouse where scanned cards are added to inventory',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Stock Location',
        domain="[('usage', '=', 'internal'), '|', ('warehouse_id', '=', warehouse_id), ('warehouse_id', '=', False)]",
        check_company=True,
        help='Default stock location (shelf) where cards are placed',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    notes = fields.Text(
        string='Notes',
    )

    # ─── Statistics (updated by webhook when batches are created) ───
    batch_count = fields.Integer(
        string='Batches',
        default=0,
    )
    last_scan_date = fields.Datetime(
        string='Last Scan',
    )
    total_cards_scanned = fields.Integer(
        string='Total Cards',
        default=0,
    )

    _sql_constraints = [
        ('api_key_unique', 'UNIQUE(api_key)', 'This API key is already assigned to another scanner!'),
    ]

    def action_refresh_stats(self):
        """Recalculate statistics from linked batches."""
        for device in self:
            batches = self.env['supertcg.batch'].sudo().search([
                ('scanner_device_id', '=', device.id),
            ])
            device.write({
                'batch_count': len(batches),
                'last_scan_date': max(batches.mapped('scanned_at')) if batches else False,
                'total_cards_scanned': sum(batches.mapped('card_count')),
            })

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id:
            self.location_id = self.warehouse_id.lot_stock_id.id
        else:
            self.location_id = False
