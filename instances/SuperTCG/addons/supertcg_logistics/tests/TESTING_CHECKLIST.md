# SuperTCG Logistics - Full Flow Testing Checklist

## Environment
- **URL**: https://dev.supertcg.be/
- **Backend**: https://dev.supertcg.be/web
- **Test Product**: Pokemon TCG Trick Or Trade Booster (ID: 22700)
- **Expected Stock**: Leuven 122 (1), Leuven 49 (6) = Total 7
- **Pickup Max**: 6 units | **Delivery Max**: 7 units

---

## Phase 1: Product Page

- [ ] Open https://dev.supertcg.be/shop/pokemon-pokemon-tcg-trick-or-trade-booster-eng-22700
- [ ] **Hard refresh** (Ctrl+F5)
- [ ] Verify page loads without 500 error
- [ ] Verify "Available in" box shows: `Leuven 122 (1), Leuven 49 (6)`
- [ ] Verify pickup note shows: `Max for store pickup: 6 | Total for delivery: 7`
- [ ] Click + button 8 times → quantity should stop at 7
- [ ] Click - button → quantity should decrease
- [ ] Type 999 in quantity field → should cap to 7
- [ ] Click **"Add to Cart"** with qty 7

---

## Phase 2: Cart Page

- [ ] Go to https://dev.supertcg.be/shop/cart
- [ ] Verify quantity shows 7
- [ ] Click + button → should not increase (blocked by JS)
- [ ] Manually type 999 in quantity field → should cap to 7
- [ ] Verify price updates correctly
- [ ] Click **"Checkout"**

---

## Phase 3: Checkout - Delivery

- [ ] Verify checkout page loads
- [ ] Select **"Pick up in store"**
- [ ] Verify all 4 stores appear:
  - [ ] SuperTCG - Leuven 122
  - [ ] SuperTCG - Leuven 49
  - [ ] SuperTCG - Mechelen
  - [ ] SuperTCG - Hasselt
- [ ] Select a store (e.g., Leuven 49)
- [ ] Shipping cost should show `0.00` (pickup is free)

### Delivery Option (Optional)
- [ ] Select **"Standard delivery"** or **"Bpost service point"**
- [ ] Bpost will show OAuth error (dev only — expected)
- [ ] Standard delivery should show price

---

## Phase 4: Checkout - Payment

- [ ] Select **"Wire Transfer"** or **"Demo"** payment method
- [ ] Click **"Pay Now"**
- [ ] Order should be confirmed
- [ ] You should see order confirmation page with reference number

---

## Phase 5: Backend Verification

### 5.1 Sales Order
- [ ] Log in to https://dev.supertcg.be/web
- [ ] Go to **Sales → Orders**
- [ ] Find your order (reference from confirmation page)
- [ ] Open the order and verify:
  - [ ] **Customer**: Your test customer
  - [ ] **Warehouse**: Should be the store with most stock (e.g., Leuven 49)
  - [ ] **Order Lines** → Product: Trick Or Trade Booster
  - [ ] **Quantity**: 7
  - [ ] **Suggested Warehouse** column shows the assigned store

### 5.2 Delivery Order (Picking)
- [ ] From the Sales Order, click the **Delivery** smart button
- [ ] Or go to **Inventory → Operations → Deliveries**
- [ ] Verify:
  - [ ] Source Location: `WH/[Store Name]/Stock` (not "My Company")
  - [ ] Product: Trick Or Trade Booster
  - [ ] Quantity: 7
  - [ ] Status: Ready or Done

### 5.3 Stock Deduction
- [ ] Go to **Inventory → Products → Products**
- [ ] Search for "Trick Or Trade"
- [ ] Verify stock was deducted from the assigned warehouse only

### 5.4 Invoice
- [ ] Go to **Invoicing → Invoices**
- [ ] Find invoice for your order
- [ ] Verify:
  - [ ] Product: Trick Or Trade Booster
  - [ ] Quantity: 7
  - [ ] Amount correct

### 5.5 Multi-Warehouse Shipping (Optional)
- [ ] Add 2 different products to cart
- [ ] Products should be assigned to different warehouses
- [ ] At checkout, delivery cost should be **doubled** (× number of warehouses)
- [ ] Verify 2 delivery orders are created (one per warehouse)

---

## Phase 6: Edge Cases

- [ ] **Add 0 quantity**: No error, nothing added
- [ ] **Remove from cart (qty to 0)**: Line removed, no error
- [ ] **Add beyond max with "Buy Now"**: Silently capped to max
- [ ] **Pickup with qty 7**: Should show "out of stock" at all stores (max single store = 6)
- [ ] **Pickup with qty 6**: Should work at Leuven 49

---

## Known Dev Limitations

| Issue | Reason | On Production |
|---|---|---|
| Bpost OAuth error | Dev credentials invalid | ✅ Will work |
| "No payment providers" (before fix) | Not configured | ✅ Configured |
| SendCloud errors | Dev API sandbox | ✅ Live API |

---

## How to Reset Test Data

If you need to clean up test orders:

1. Go to **Sales → Orders**
2. Filter by your test customer
3. Select orders → Action → **Cancel**
4. Or delete if still in draft

---

## Quick Commands (for developers)

```bash
# Run automated tests
docker compose exec odoo18-dev python3 /home/extra-others/supertcg_logistics/tests/test_supertcg_logistics.py

# Run full flow simulation
docker compose exec odoo18-dev python3 /home/extra-others/supertcg_logistics/tests/test_full_flow.py
```
