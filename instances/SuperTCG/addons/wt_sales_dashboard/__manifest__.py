# -*- coding: utf-8 -*-
{
    'name': "Sales & Inventory Dashboard",
    'version': '18.0.0.1',
    'summary': """
        A modern, visual dashboard for sales and stock metrics.
    """,
    'description': """
        This module provides a comprehensive dashboard with KPI cards, charts,
        and recent sales data to give you a clear overview of your business performance.
        Built with the OWL framework for a responsive experience.
    """,
    'author': "Warlock Technologies Pvt Ltd.",
    'website': "http://www.warlocktechnologies.com",
    'category': 'Sales/Sales',
    'depends': ['web', 'sale_management', 'stock'],
    'data': [
        'views/sales_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js',
            'wt_sales_dashboard/static/src/dashboard.js',
            'wt_sales_dashboard/static/src/dashboard.xml',
            'wt_sales_dashboard/static/src/dashboard.css',
        ],
    },
    "images": ["static/description/screen_image.png"],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
