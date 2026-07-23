{
    "name": "SuperTCG Logistics",
    "version": "18.0.1.0.6",
    "category": "Warehouse",
    "summary": "Multi-warehouse stock aggregation for e-commerce",
    "description": "Aggregate stock across multiple store warehouses for e-commerce, "
    "show store availability on product pages, and multiply delivery "
    "costs when shipping from multiple warehouses.",
    "author": "SuperTCG",
    "license": "LGPL-3",
    "website": "https://dev.supertcg.be",
    "depends": [
        "website_sale_stock",
        "website_sale",
        "stock",
        "delivery",
    ],
    "data": [
        "views/product_templates.xml",
        "views/cart_templates.xml",
        "views/assets.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
