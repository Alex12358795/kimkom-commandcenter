#!/usr/bin/env python3
"""
Comprehensive test suite for supertcg_logistics module.
Run this script to verify all functionality works correctly.
"""

import odoo
from odoo.tools import config

config.parse_config(
    [
        "-c",
        "/etc/odoo/odoo.conf",
        "--db_host",
        "db-dev",
        "--db_port",
        "5432",
        "--db_user",
        "odoo",
        "--db_password",
        "odoo18@2024",
    ]
)

odoo.service.server.load_server_wide_modules()
registry = odoo.modules.registry.Registry.new("odoo")

PASS = 0
FAIL = 0


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: {detail}")


with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})

    print("=" * 70)
    print("SUPERTCG LOGISTICS - COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    # Find test product
    product = env["product.product"].search(
        [("name", "ilike", "trick or trade")], limit=1
    )
    test("Test product found", product.exists(), "No product found")
    if not product.exists():
        print("ABORTING - no test product")
        exit(1)

    print(f"\nTest product: {product.name} (ID: {product.id})")

    # ========================================================================
    print("\n[TEST 1] Warehouse Availability Methods")
    # ========================================================================
    avail = product._get_warehouse_availability()
    test("_get_warehouse_availability returns list", isinstance(avail, list))
    test(
        "At least one warehouse has stock",
        len(avail) > 0,
        f"Got {len(avail)} warehouses",
    )

    max_qty = product._get_website_max_qty()
    test("_get_website_max_qty > 0", max_qty > 0, f"Got {max_qty}")

    tmpl = product.product_tmpl_id
    tmpl_avail = tmpl._get_warehouse_availability()
    test("Template _get_warehouse_availability works", isinstance(tmpl_avail, list))
    tmpl_max = tmpl._get_website_max_qty()
    test("Template _get_website_max_qty > 0", tmpl_max > 0, f"Got {tmpl_max}")

    # ========================================================================
    print("\n[TEST 2] Add to Cart Possibility")
    # ========================================================================
    possible = product._is_add_to_cart_possible()
    test("_is_add_to_cart_possible returns True", possible)

    website = env["website"].search([], limit=1)
    if website:
        web_qty = website._get_product_available_qty(product)
        test("Website aggregated qty > 0", web_qty > 0, f"Got {web_qty}")
        test(
            "Website qty matches max_qty",
            web_qty == max_qty,
            f"web_qty={web_qty}, max_qty={max_qty}",
        )

    # ========================================================================
    print("\n[TEST 3] Cart Update Validation")
    # ========================================================================
    partner = env["res.partner"].search([], limit=1)

    def create_cart():
        return env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": 1})
                ],
            }
        )

    # Test 3a: add_qty=0 should not raise
    so = create_cart()
    try:
        so._cart_update(product_id=product.id, add_qty=0)
        test("add_qty=0: no error", True)
    except Exception as e:
        test("add_qty=0: no error", False, str(e))
    so.unlink()

    # Test 3b: add_qty=-1 (remove) should not raise
    so = create_cart()
    try:
        so._cart_update(product_id=product.id, add_qty=-1)
        test("add_qty=-1: no error", True)
    except Exception as e:
        test("add_qty=-1: no error", False, str(e))
    so.unlink()

    # Test 3c: add within limit should work
    so = create_cart()  # starts with 1
    try:
        so._cart_update(product_id=product.id, add_qty=1)  # total = 2
        line_qty = sum(
            so.order_line.filtered(lambda l: l.product_id == product).mapped(
                "product_uom_qty"
            )
        )
        test("add within limit: allowed", line_qty == 2, f"Got qty={line_qty}")
    except Exception as e:
        test("add within limit: allowed", False, str(e))
    so.unlink()

    # Test 3d: add beyond limit should be silently capped
    so = create_cart()  # starts with 1
    try:
        so._cart_update(product_id=product.id, add_qty=max_qty + 10)
        line_qty = sum(
            so.order_line.filtered(lambda l: l.product_id == product).mapped(
                "product_uom_qty"
            )
        )
        test(
            "add beyond limit: capped silently",
            line_qty == max_qty,
            f"Got qty={line_qty}, expected={max_qty}",
        )
    except Exception as e:
        test("add beyond limit: capped silently", False, str(e))
    so.unlink()

    # Test 3e: set_qty within limit should work
    so = create_cart()  # starts with 1
    line = so.order_line.filtered(lambda l: l.product_id == product)
    try:
        so._cart_update(product_id=product.id, line_id=line.id, set_qty=2)
        test("set_qty within limit: allowed", True)
    except Exception as e:
        test("set_qty within limit: allowed", False, str(e))
    so.unlink()

    # Test 3f: set_qty beyond limit should be silently capped
    so = create_cart()  # starts with 1
    line = so.order_line.filtered(lambda l: l.product_id == product)
    try:
        so._cart_update(product_id=product.id, line_id=line.id, set_qty=max_qty + 10)
        line_qty = sum(
            so.order_line.filtered(lambda l: l.product_id == product).mapped(
                "product_uom_qty"
            )
        )
        test(
            "set_qty beyond limit: capped silently",
            line_qty == max_qty,
            f"Got qty={line_qty}, expected={max_qty}",
        )
    except Exception as e:
        test("set_qty beyond limit: capped silently", False, str(e))
    so.unlink()

    # Test 3g: add exact limit to empty cart should work
    so = env["sale.order"].create({"partner_id": partner.id})
    try:
        so._cart_update(product_id=product.id, add_qty=max_qty)
        line_qty = sum(
            so.order_line.filtered(lambda l: l.product_id == product).mapped(
                "product_uom_qty"
            )
        )
        test(
            f"add exact limit ({max_qty}) to empty cart: allowed",
            line_qty == max_qty,
            f"Got qty={line_qty}",
        )
    except Exception as e:
        test(f"add exact limit ({max_qty}) to empty cart: allowed", False, str(e))
    so.unlink()

    # ========================================================================
    print("\n[TEST 4] Warehouse Assignment on Order Lines")
    # ========================================================================
    so = create_cart()
    line = so.order_line[0]
    test(
        "Line has suggested_warehouse_id",
        bool(line.suggested_warehouse_id),
        f"Got {line.suggested_warehouse_id.name if line.suggested_warehouse_id else 'None'}",
    )
    so.unlink()

    # ========================================================================
    print("\n[TEST 5] Delivery Cost Multiplier")
    # ========================================================================
    carrier = env["delivery.carrier"].search(
        [("name", "not ilike", "pick up")], limit=1
    )
    if carrier:
        # Single warehouse order
        so = create_cart()
        rate = carrier.rate_shipment(so)
        so.carrier_id = carrier.id
        so._create_delivery_line(carrier, rate["price"])
        delivery_line = so.order_line.filtered(lambda l: l.is_delivery)
        test("Single warehouse: delivery line created", bool(delivery_line))
        so.unlink()

        # Multi-warehouse order
        product2 = env["product.product"].search([("id", "!=", product.id)], limit=1)
        so = env["sale.order"].create(
            {
                "partner_id": partner.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": product2.id, "product_uom_qty": 1}),
                ],
            }
        )
        wh_count = so._get_warehouse_count()
        test(f"Multi-warehouse: count = {wh_count}", wh_count >= 1)
        so.unlink()
    else:
        print("  [SKIP] No paid carrier found for delivery test")

    # ========================================================================
    print("\n[TEST 6] Pickup Carrier Configuration")
    # ========================================================================
    pickup_carrier = env["delivery.carrier"].browse(4)
    test("Pickup carrier exists", pickup_carrier.exists())
    wh_names = [wh.name for wh in pickup_carrier.warehouse_ids]
    test(
        "Pickup has 4 warehouses",
        len(wh_names) == 4,
        f"Got {len(wh_names)}: {wh_names}",
    )
    test("Pickup includes Hasselt", any("Hasselt" in n for n in wh_names))

    # ========================================================================
    print("\n[TEST 7] Active Views")
    # ========================================================================
    view1 = env.ref(
        "supertcg_logistics.product_warehouse_availability", raise_if_not_found=False
    )
    view2 = env.ref("supertcg_logistics.product_quantity_max", raise_if_not_found=False)
    test("Availability view active", view1 and view1.active)
    test("Quantity max view active", view2 and view2.active)

    # ========================================================================
    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 70)

    cr.commit()

    if FAIL > 0:
        exit(1)
    else:
        print("\nALL TESTS PASSED!")
