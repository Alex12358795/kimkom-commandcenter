# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime, timedelta


class SalesDashboard(models.AbstractModel):
    _name = 'wt.sales.dashboard'
    _description = 'Sales & Inventory Dashboard Model'

    @api.model
    def get_dashboard_data(self):
        """
        Main method to fetch all data required for the dashboard.
        """
        # Get data for the last 30 days
        last_30_days_start = datetime.now() - timedelta(days=30)
        
        # KPI Data
        sales_orders = self.env['sale.order'].search([
            ('date_order', '>=', last_30_days_start),
            ('state', 'in', ['sale', 'done'])
        ])
        
        total_sales = sum(sales_orders.mapped('amount_total'))
        order_count = len(sales_orders)
        avg_order_value = total_sales / order_count if order_count > 0 else 0
        
        low_stock_products = self.env['product.product'].search_count([
            ('type', '=', 'consu'),('is_storable','=',True),
            ('qty_available', '<=', 10) # Example threshold
        ])

        # Chart Data: Sales over time
        sales_by_day = {}
        for i in range(30):
            day = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            sales_by_day[day] = 0
        
        for order in sales_orders:
            day = order.date_order.strftime('%Y-%m-%d')
            if day in sales_by_day:
                sales_by_day[day] += order.amount_total
        
        sales_trend_labels = sorted(sales_by_day.keys())
        sales_trend_data = [sales_by_day[key] for key in sales_trend_labels]

        # Chart Data: Top 5 Selling Products
        top_products_query = """
            SELECT sol.product_id, SUM(sol.product_uom_qty) as total_qty
            FROM sale_order_line sol
            JOIN sale_order so ON sol.order_id = so.id
            WHERE so.date_order >= %s AND so.state IN ('sale', 'done') AND sol.product_id IS NOT NULL
            GROUP BY sol.product_id
            ORDER BY total_qty DESC
            LIMIT 5
        """
        self.env.cr.execute(top_products_query, (last_30_days_start,))
        top_products_data = self.env.cr.dictfetchall()

        product_ids = [p['product_id'] for p in top_products_data]
        # Use the ORM to correctly fetch product names, avoiding translation issues
        products = self.env['product.product'].browse(product_ids)
        product_name_map = {p.id: p.display_name for p in products}

        top_products_labels = [product_name_map.get(p['product_id'], 'Unknown') for p in top_products_data]
        top_products_values = [p['total_qty'] for p in top_products_data]

        # Recent Sales Orders
        recent_orders = self.env['sale.order'].search([
            ('state', 'in', ['sale', 'done'])
        ], order='date_order desc', limit=5)
        
        recent_orders_data = [{
            'id': order.id,
            'name': order.name,
            'partner': order.partner_id.name,
            'date': order.date_order.strftime('%Y-%m-%d'),
            'total': order.amount_total,
            'state': dict(order._fields['state'].selection).get(order.state)
        } for order in recent_orders]

        return {
            'kpis': {
                'total_sales': total_sales,
                'avg_order_value': avg_order_value,
                'order_count': order_count,
                'low_stock_products': low_stock_products,
            },
            'charts': {
                'sales_trend': {
                    'labels': sales_trend_labels,
                    'data': sales_trend_data,
                },
                'top_products': {
                    'labels': top_products_labels,
                    'data': top_products_values,
                }
            },
            'recent_orders': recent_orders_data
        }
