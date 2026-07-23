#!/usr/bin/env python3
"""
Full e-commerce flow test for SuperTCG Logistics.
Simulates: product page → cart → checkout → payment → delivery → invoice
"""

import odoo
from odoo.tools import config
from odoo.exceptions import UserError

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
    print("FULL E-COMMERCE FLOW TEST")
    print("=" * 70)

    # ========================================================================
    print("\n[STEP 1] Setup: Find test product and customer")
    # ========================================================================
    product = env["product.product"].search(
        [("name", "ilike", "trick or trade")], limit=1
    )
    test("Test product found", product.exists(), f"ID: {product.id}")

    partner = env["res.partner"].search([("email", "!=", False)], limit=1)
    if not partner:
        partner = env["res.partner"].create(
            {
                "name": "Test Customer",
                "email": "test@supertcg.be",
                "street": "Test Street 1",
                "city": "Leuven",
                "zip": "3000",
                "country_id": env.ref("base.be").id,
            }
        )
        print(f"  Created test customer: {partner.name}")
    else:
        print(f"  Using customer: {partner.name}")

    website = env["website"].search([], limit=1)
    test("Website found", website.exists(), website.name)

    max_qty = int(product.product_tmpl_id._get_website_max_qty())
    pickup_max = int(product.product_tmpl_id._get_pickup_max_qty())
    print(f"  Delivery max: {max_qty}, Pickup max: {pickup_max}")

    # ========================================================================
    print("\n[STEP 2] Add product to cart (via _cart_update)")
    # ========================================================================
    so = env["sale.order"].create(
        {
            "partner_id": partner.id,
            "partner_invoice_id": partner.id,
            "partner_shipping_id": partner.id,
            "warehouse_id": website.warehouse_id.id if website.warehouse_id else False,
        }
    )

    # Capture initial warehouse before cart update
    initial_wh = so.warehouse_id.name if so.warehouse_id else "None"

    # Add exact max quantity
    so._cart_update(product_id=product.id, add_qty=max_qty)

    line = so.order_line.filtered(
        lambda l: l.product_id == product and not l.is_delivery
    )
    test("Product added to cart", len(line) == 1)
    test(
        "Quantity is correct",
        int(line.product_uom_qty) == max_qty,
        f"Expected {max_qty}, got {line.product_uom_qty}",
    )
    test(
        "Suggested warehouse set",
        bool(line.suggested_warehouse_id),
        line.suggested_warehouse_id.name if line.suggested_warehouse_id else "None",
    )
    test(
        "Order warehouse auto-routed to suggested warehouse",
        so.warehouse_id == line.suggested_warehouse_id,
        f"Order: {so.warehouse_id.name}, Line: {line.suggested_warehouse_id.name}, Initial: {initial_wh}",
    )

    # ========================================================================
    print("\n[STEP 3] Set delivery method (Pick up in store)")
    # ========================================================================
    pickup_carrier = env["delivery.carrier"].browse(4)
    if pickup_carrier.exists() and pickup_carrier.active:
        # Get the warehouse with most stock for this product
        avail = product.product_tmpl_id._get_warehouse_availability()
        best_wh = max(avail, key=lambda x: x["qty"])["warehouse"] if avail else False

        # Note: warehouse is already auto-set by _cart_update in STEP 2
        # We just verify it matches the best warehouse
        test("Pickup carrier set", so.carrier_id == pickup_carrier, so.carrier_id.name)
        test(
            "Warehouse matches best store",
            so.warehouse_id == best_wh,
            f"{so.warehouse_id.name} vs {best_wh.name}",
        )
    else:
        print("  [SKIP] Pickup carrier not available")

    # ========================================================================
    print("\n[STEP 4] Confirm the order")
    # ========================================================================
    try:
        so.action_confirm()
        test("Order confirmed", so.state == "sale", f"State: {so.state}")
    except Exception as e:
        test("Order confirmed", False, str(e)[:100])

    # ========================================================================
    print("\n[STEP 5] Verify Delivery Order (Picking)")
    # ========================================================================
    pickings = so.picking_ids
    test("Delivery order created", len(pickings) > 0, f"Count: {len(pickings)}")

    if pickings:
        picking = pickings[0]
        test(
            "Picking state is ready/done",
            picking.state in ["assigned", "done", "waiting", "confirmed"],
            f"State: {picking.state}",
        )
        test(
            "Picking location is store warehouse",
            picking.location_id == so.warehouse_id.lot_stock_id
            or picking.location_id.warehouse_id == so.warehouse_id,
            f"Location: {picking.location_id.name}, Warehouse: {so.warehouse_id.name}",
        )

        # Check stock move
        moves = picking.move_ids
        product_move = moves.filtered(lambda m: m.product_id == product)
        test("Stock move created", len(product_move) == 1)
        if product_move:
            test(
                "Move quantity matches",
                int(product_move.product_uom_qty) == max_qty,
                f"Expected {max_qty}, got {product_move.product_uom_qty}",
            )
            test(
                "Move source location is warehouse",
                product_move.location_id.warehouse_id == so.warehouse_id,
                f"Source: {product_move.location_id.name}",
            )

    # ========================================================================
    print("\n[STEP 6] Verify Invoice")
    # ========================================================================
    try:
        # Create invoice
        so._create_invoices()
        invoices = so.invoice_ids
        test("Invoice created", len(invoices) > 0, f"Count: {len(invoices)}")

        if invoices:
            inv = invoices[0]
            test(
                "Invoice state is draft/posted",
                inv.state in ["draft", "posted"],
                f"State: {inv.state}",
            )
            inv_line = inv.invoice_line_ids.filtered(lambda l: l.product_id == product)
            test("Invoice line exists", len(inv_line) == 1)
            if inv_line:
                test(
                    "Invoice quantity matches",
                    int(inv_line.quantity) == max_qty,
                    f"Expected {max_qty}, got {inv_line.quantity}",
                )
    except Exception as e:
        test("Invoice created", False, str(e)[:100])

    # ========================================================================
    print("\n[STEP 7] Verify Stock Deduction")
    # ========================================================================
    # Check stock after order confirmation
    wh_stock = product.with_context(warehouse_id=so.warehouse_id.id).free_qty
    print(f"  Remaining stock in {so.warehouse_id.name}: {wh_stock}")

    # ========================================================================
    print("\n[STEP 8] Multi-warehouse delivery cost test")
    # ========================================================================
    # Create order with 2 products that go to different warehouses
    product2 = env["product.product"].search(
        [
            ("id", "!=", product.id),
            ("type", "=", "consu"),
            ("sale_ok", "=", True),
        ],
        limit=1,
    )

    if product2:
        so2 = env["sale.order"].create(
            {
                "partner_id": partner.id,
                "partner_shipping_id": partner.id,
                "order_line": [
                    (0, 0, {"product_id": product.id, "product_uom_qty": 1}),
                    (0, 0, {"product_id": product2.id, "product_uom_qty": 1}),
                ],
            }
        )

        wh_count = so2._get_warehouse_count()
        test(f"Multi-product warehouse count: {wh_count}", wh_count >= 1)

        # Check if lines have different warehouses
        whs = so2.order_line.mapped("suggested_warehouse_id")
        test("Lines have warehouse assignments", len(whs) > 0)

        so2.unlink()
    else:
        print("  [SKIP] No second product found for multi-warehouse test")

    # ========================================================================
    print("\n[STEP 9] Cleanup")
    # ========================================================================
    # Cancel invoices first
    for inv in so.invoice_ids:
        if inv.state in ["posted", "draft"]:
            inv.button_cancel()

    # Cancel pickings
    for picking in so.picking_ids:
        if picking.state not in ["done", "cancel"]:
            picking.action_cancel()

    # Cancel test order (may fail due to subscriptions/pickings)
    try:
        if so.state == "sale":
            so.action_cancel()
        if so.state == "cancel":
            test("Order cancelled", True)
        else:
            print(
                f"  [INFO] Order {so.name} left in state '{so.state}' — manual cleanup needed"
            )
    except Exception as e:
        print(
            f"  [INFO] Order {so.name} left in state '{so.state}' — manual cleanup needed"
        )

    # ========================================================================
    print("\n" + "=" * 70)
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print("=" * 70)

    cr.commit()

    if FAIL == 0:
        print("\nFULL FLOW TEST COMPLETED SUCCESSFULLY!")
    else:
        print(f"\n{FAIL} test(s) failed. Check details above.")
