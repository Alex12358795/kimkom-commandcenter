/** @odoo-module **/

import { Component, onWillStart, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class SalesDashboard extends Component {
    static template = "wt_sales_dashboard.SalesDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = {
            kpis: {},
            charts: {},
            recent_orders: [],
        };
        
        this.salesTrendChartRef = useRef("salesTrendChart");
        this.topProductsChartRef = useRef("topProductsChart");

        onWillStart(async () => {
            const data = await this.orm.call("wt.sales.dashboard", "get_dashboard_data", []);
            this.state.kpis = data.kpis;
            this.state.charts = data.charts;
            this.state.recent_orders = data.recent_orders;
        });

        onMounted(() => {
            this.renderCharts();
        });
    }

    renderCharts() {
        if (this.salesTrendChartRef.el) {
            new Chart(this.salesTrendChartRef.el, {
                type: 'line',
                data: {
                    labels: this.state.charts.sales_trend.labels,
                    datasets: [{
                        label: 'Sales (Last 30 Days)',
                        data: this.state.charts.sales_trend.data,
                        borderColor: '#4F46E5',
                        backgroundColor: 'rgba(79, 70, 229, 0.1)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                }
            });
        }

        if (this.topProductsChartRef.el) {
            new Chart(this.topProductsChartRef.el, {
                type: 'bar',
                data: {
                    labels: this.state.charts.top_products.labels,
                    datasets: [{
                        label: 'Quantity Sold',
                        data: this.state.charts.top_products.data,
                        backgroundColor: ['#10B981', '#3B82F6', '#F59E0B', '#EF4444', '#8B5CF6'],
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    layout: {
                        padding: {
                            left: 20
                        }
                    }
                }
            });
        }
    }
    
    openSaleOrder(orderId) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'sale.order',
            res_id: orderId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openTotalSales() {
        const date = new Date();
        date.setDate(date.getDate() - 30);
        const thirtyDaysAgo = date.toISOString().split('T')[0];
        
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Sales Orders (Last 30 Days)',
            res_model: 'sale.order',
            views: [[false, 'list'], [false, 'form']],
            domain: [['date_order', '>=', thirtyDaysAgo], ['state', 'in', ['sale', 'done']]],
            target: 'current',
        });
    }

    openTotalOrders() {
        this.openTotalSales();
    }

    openLowStockProducts() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Low Stock Products',
            res_model: 'product.product',
            views: [[false, 'list'], [false, 'form']],
            domain: [['type', '=', 'consu'], ['qty_available', '<=', 10]],
            target: 'current',
        });
    }
}

registry.category("actions").add("wt_sales_dashboard.dashboard", SalesDashboard);
