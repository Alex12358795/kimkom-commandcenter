{
    'name': 'SuperTCG Scanner',
    'version': '18.0.4.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Webhook receiver for SuperTCG card scanner batches',
    'description': """
Receive scanned card batches from Raspberry Pi scanner sidecars.
Store raw card data, review batches, add to inventory, and print barcode labels via Pi API.

Features:
- Public webhook endpoint with API key authentication
- Raw card data storage for review before processing
- Per-card include/exclude toggles with visual indicators
- Direct stock quant updates (no picking)
- Buylist PDF generation with card images and pricing
- ZPL barcode label printing via Pi direct API
- Multi-company ready for future store scaling

See CHANGELOG.md for detailed issue documentation and production notes.
    """,
    'author': 'SuperTCG',
    'license': 'LGPL-3',
    'website': 'https://dev.supertcg.be',
    'depends': [
        'base',
        'product',
        'stock',
        'base_setup',
        'supertcg_products',
    ],
    'data': [
        'security/supertcg_scanner_security.xml',
        'security/ir.model.access.csv',
        'views/supertcg_batch_views.xml',
        'views/res_config_settings_views.xml',
        'views/hub_dashboard_inherit.xml',
        'report/buylist_report_template.xml',
        'report/buylist_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'supertcg_scanner/static/src/css/scanner_backend.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
