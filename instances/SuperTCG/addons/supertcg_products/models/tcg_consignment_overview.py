from odoo import api, fields, models


class TcgConsignmentOverview(models.Model):
    _name = 'tcg.consignment.overview'
    _description = 'Consignment Overview'
    _auto = False
    _order = 'partner_id, product_id'

    partner_id = fields.Many2one('res.partner', string='Owner', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_name = fields.Char(string='Product Name', readonly=True)
    category_id = fields.Many2one('product.category', string='Category', readonly=True)
    received_qty = fields.Float(string='Received', readonly=True)
    sold_qty = fields.Float(string='Sold', readonly=True)
    in_stock_qty = fields.Float(string='In Stock', readonly=True)
    cost_price = fields.Float(string='Cost Price', readonly=True)
    total_settlement = fields.Float(string='Settlement Amount', readonly=True)
    location_id = fields.Many2one('stock.location', string='Stock Location', readonly=True)

    def init(self):
        self._cr.execute("DROP VIEW IF EXISTS tcg_consignment_overview CASCADE")
        self._cr.execute("""
            CREATE VIEW tcg_consignment_overview AS
            WITH received AS (
                SELECT
                    sm.restrict_partner_id AS partner_id,
                    sm.product_id,
                    sm.company_id,
                    SUM(sm.product_uom_qty) AS received_qty,
                    MAX(COALESCE(
                        sm.price_unit,
                        (pp.standard_price->>sm.company_id::text)::numeric,
                        0
                    )) AS cost_price
                FROM stock_move sm
                JOIN stock_picking sp ON sm.picking_id = sp.id
                JOIN product_product pp ON sm.product_id = pp.id
                WHERE sp.origin ILIKE '%%TCG Consignment%%'
                    AND sm.state = 'done'
                    AND sm.restrict_partner_id IS NOT NULL
                GROUP BY sm.restrict_partner_id, sm.product_id, sm.company_id
            ),
            delivered AS (
                SELECT
                    sm.product_id,
                    SUM(sm.product_uom_qty) AS delivered_qty
                FROM stock_move sm
                JOIN stock_picking_type spt ON sm.picking_type_id = spt.id
                WHERE sm.state = 'done'
                    AND spt.code = 'outgoing'
                GROUP BY sm.product_id
            ),
            product_locations AS (
                SELECT
                    sq.product_id,
                    sq.owner_id,
                    sq.location_id,
                    SUM(sq.quantity) AS qty
                FROM stock_quant sq
                JOIN stock_location sl ON sq.location_id = sl.id
                WHERE sl.usage = 'internal'
                    AND sq.owner_id IS NOT NULL
                GROUP BY sq.product_id, sq.owner_id, sq.location_id
            ),
            best_location AS (
                SELECT DISTINCT ON (pl.product_id, pl.owner_id)
                    pl.product_id,
                    pl.owner_id,
                    pl.location_id
                FROM product_locations pl
                ORDER BY pl.product_id, pl.owner_id, pl.qty DESC
            )
            SELECT
                row_number() OVER () AS id,
                r.partner_id,
                r.product_id,
                pt.name->>'en_US' AS product_name,
                pt.categ_id AS category_id,
                r.received_qty,
                LEAST(r.received_qty, COALESCE(d.delivered_qty, 0)) AS sold_qty,
                GREATEST(r.received_qty - LEAST(r.received_qty, COALESCE(d.delivered_qty, 0)), 0) AS in_stock_qty,
                r.cost_price,
                r.cost_price * LEAST(r.received_qty, COALESCE(d.delivered_qty, 0)) AS total_settlement,
                bl.location_id
            FROM received r
            LEFT JOIN delivered d ON r.product_id = d.product_id
            JOIN product_product pp ON r.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN best_location bl ON r.product_id = bl.product_id AND r.partner_id = bl.owner_id
        """)
