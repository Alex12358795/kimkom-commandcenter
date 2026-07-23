# SuperTCG Scanner Changelog

## 18.0.1.9.0 — Search, Stats & Product Links

**Date:** 2025-05-25  
**Status:** Production Ready

### 🔧 Changed
- **Batch search fixed:** "Group By Device" now groups by `scanner_device_id` (real link) instead of old `device_id` text. Added Store filter.
- **All Cards search added:** Search by card name, game, set, product ID, batch. Filters: Included/Excluded, Mismatch, In Inventory/Not in Inventory. Group by Game, Set, Batch, Store.
- **Batch card form reorganized:** Store, Batch, Scanner info moved to a prominent "Source" section at the top of the card form.
- **Scanner device stats:** List view now shows Batches, Total Cards, Last Scan columns.
- **"Open Product" button:** Added to batch card list (inside batch form), All Cards list, and card form. Opens the linked inventory product directly. Only shows when product exists.

---

## 18.0.1.8.0 — Batch Update Support (Incremental Sync)

**Date:** 2025-05-25  
**Status:** Production Ready

### 🔧 Changed
- **Batches can now receive updates.** Instead of rejecting duplicate `batch_id`, the webhook now merges changes:
  - **New cards** in the payload → created
  - **Existing cards** (matched by `external_product_id`) → only changed fields updated
  - **Unchanged cards** → left alone (including user's `is_included` toggle)
- **Smart field comparison:** Only writes fields that actually changed. Floats compared with 0.001 tolerance.
- **Response now reports:** `created`, `updated`, `unchanged`, `errors`
- **Never overwrites user-managed fields:** `is_included` and `product_product_id` are preserved.

---

## 18.0.1.7.0 — One Scanner = One Complete Flow

**Date:** 2025-05-25  
**Status:** Production Ready

### 🔧 Changed
- **Scanner Device now defines the complete flow:** Store + Warehouse + Location + Printer.
- **No more manual warehouse/location selection per batch.** The webhook auto-sets warehouse/location from the scanner device mapping.
- **Added `scanner_device_id` on Batch** — clickable link to the scanner config.
- **Batch warehouse/location are now readonly** — set automatically, visible for info only.
- **Added multi-company record rule for Scanner Devices** — Store A staff can't see Store B's scanner configs.
- **"All Cards" view** now shows Store column.
- **Scanner Device form** reorganized: Scanner (API key, Store) → Inventory Location (Warehouse, Location) → Label Printer.

---

## 18.0.1.6.0 — Scanner Device Form Simplification

**Date:** 2025-05-25  
**Status:** Production Ready

### 🔧 Changed
- **Removed `device_id` field** from Scanner Device mapping. The Pi authenticates via `X-API-Key` header only — `device_id` was redundant and confusing.
- **Simplified Scanner Device form:** Name, API Key, Store, Printer. No more `device_id` to type.
- **Simplified `_get_label_printer()`**: Removed device_id fallback lookup. The webhook already sets `printer_id` directly from the scanner mapping at batch creation.
- **Consistent "Store" labeling**: `company_id` is labeled "Store" everywhere (not "Company").
- **`device_id` kept on Batch model** as optional debug info — the Pi still sends it in the payload.

---

## 18.0.1.5.0 — Fresh Install Fix

**Date:** 2025-05-25  
**Status:** Production Ready

### 🔧 Fixed
- **Fresh install crash:** `action_supertcg_scanner_device` and `action_supertcg_pricing_config` were defined at the bottom of `supertcg_batch_views.xml` but referenced by `view_supertcg_batch_list` at the top. On upgrade this worked (records already existed), but on fresh install the XML parser failed with `External ID not found`.
- **Fix:** Moved both action definitions to the top of the XML file, before any views that reference them.

---

## 18.0.1.4.0 — IoT Label Printing Production Ready

**Date:** 2025-05-25  
**Status:** Production Ready — Label Printing Verified

---

### 🏷️ Summary

This release fixes end-to-end IoT label printing for Windows-based IoT boxes (AlexSnapdragon) and adds production-safe runtime patches for Odoo 18 IoT controller compatibility.

---

### 🔧 Critical Issues Fixed

#### 1. IoT Box Sends Empty MAC Address
**Symptom:** Windows IoT box registers with empty `identifier` (`""`) because `hw_drivers` picks up a virtual/VPN network interface with no MAC address.  
**Root Cause:** `helpers.get_mac_address()` in `hw_drivers` returns empty string on Windows when the first interface has no MAC.  
**Impact:**
- `/iot/setup` fails to find existing box → creates duplicate
- `/iot/log` fails to match box → logs dropped
- Label printing fails because websocket `iotIdentifiers` can't match empty MAC

**Fix (in `controllers/iot_patch_controller.py`):**
- Skip MAC search when `identifier` is empty/null to avoid matching ALL boxes with empty identifier
- Add IP fallback: if MAC search fails, search by IP address
- Always update `identifier` field on existing boxes so Odoo stores the real MAC
- Always return websocket channel (`get_iot_channel(check=False)`) even for existing boxes

**Production Note:** The real MAC (`58:cd:c9:04:27:b1`) was visible in the IoT box localhost page but never sent to Odoo. The IP fallback ensures the box is found even with empty MAC.

---

#### 2. Odoo 18 Removed `request.jsonrequest`
**Symptom:** IoT box POSTs raw JSON to `/iot/setup`, Odoo 18 crashes with `AttributeError: 'HttpRequest' object has no attribute 'jsonrequest'`.  
**Root Cause:** Odoo 18 replaced `request.jsonrequest` with `request.get_json_data()`. The `iot` module (even in Odoo 18.0+e) still uses `request.jsonrequest` in `update_box()`.  
**Impact:** IoT box `/iot/setup` calls crash on raw JSON requests (Box < V19).

**Fix (in `controllers/iot_patch_controller.py`):**
- Use `request.get_json_data()` instead of `request.jsonrequest`
- Handle both JSON-RPC envelopes (`{'params': {...}}`) and raw JSON
- Gracefully fall back if IoT module is not installed

**Production Note:** This is a runtime controller inheritance patch — no Odoo core files modified. The patch lives entirely in our module.

---

#### 3. Nginx Does Not Proxy `/websocket`
**Symptom:** IoT box gets `400 BAD REQUEST` when connecting to `/websocket`.  
**Root Cause:** Nginx (openresty on dev.supertcg.be) had no `/websocket` location block. Websocket upgrade headers were not forwarded.  
**Impact:** IoT box websocket client cannot connect → never receives `iot_action` messages → labels never print.

**Fix (Infrastructure):**
```nginx
location /websocket {
    proxy_pass http://odoo:8069/websocket;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 86400;
}
```

**Production Note:** This must be replicated in production nginx config. It is NOT a code change.

---

#### 4. hw_drivers Websocket Client Starts Only Once at Boot
**Symptom:** After fixing nginx, IoT box still doesn't receive print jobs.  
**Root Cause:** `Manager.start()` in `hw_drivers` calls `iot_client.start()` exactly once at boot time. If the first `/iot/setup` fails (because nginx wasn't proxying websockets yet), `iot_channel` is empty and the websocket thread is never started. Subsequent `/iot/setup` calls succeed but do NOT restart the websocket client.  
**Impact:** IoT box appears connected (devices show as green in Odoo) but never receives print commands.

**Fix:** Restart the IoT box after nginx `/websocket` proxy is confirmed working. There is no code fix for this — it's architectural in hw_drivers.

**Production Note:** Always restart IoT boxes after changing nginx websocket config.

---

#### 5. `_rec_name` Missing on Custom Models
**Symptom:** MCP/API calls to `supertcg.batch` crash with `Replacement index 0 out of range for positional args tuple`.  
**Root Cause:** Odoo defaults `_rec_name = 'name'`. Our models used `batch_name`, `card_name`, etc. instead of `name`. When Odoo computes `display_name`, it fails.  
**Impact:** External integrations (MCP, API, some UI components) cannot read batch records.

**Fix:**
- `supertcg.batch`: `_rec_name = 'batch_name'`
- `supertcg.batch.card`: `_rec_name = 'card_name'`
- `supertcg.batch.log`: `_rec_name = 'message'`
- `supertcg.pricing.config`: Added computed `name` field based on `company_id.name`

---

#### 6. Pricing Compute Not Triggering During Webhook Create
**Symptom:** Cards created via webhook have `purchase_price = 0.0` and `sales_price = 0.0`.  
**Root Cause:** `_compute_pricing` depends on `batch_id.company_id` (a related field). During webhook create, the related field chain may not be fully resolved when compute triggers.  
**Impact:** All cards from Pi have zero pricing.

**Fix (in `controllers/webhook_controller.py`):**
- Calculate pricing directly in `_create_card_line()` using `supertcg.pricing.config.apply_formula()`
- Added `card_count` write flush after creating all card lines to ensure computed fields trigger

---

#### 7. Missing `urllib.request` Import
**Symptom:** CDN image download fails silently. Cards have no images.  
**Root Cause:** `webhook_controller.py` uses `urllib.request.Request` and `urllib.request.urlopen` but never imported `urllib.request`.  
**Impact:** `NameError` caught by generic exception handler → images silently missing.

**Fix:** Added `import urllib.request` at top of `webhook_controller.py`.

---

#### 8. `_send_zpl_to_iot` Missing Empty MAC Fallback
**Symptom:** Label print jobs sent but IoT box never prints.  
**Root Cause:** `_send_zpl_to_iot` only sent the box's real MAC in `iotIdentifiers`. The Windows IoT box reports empty MAC to itself, so it never matched incoming messages.  
**Impact:** Print jobs sent to bus channel but filtered out by IoT box.

**Fix (in `models/supertcg_batch.py`):**
- Build `iotIdentifiers` list with both real MAC (if any) AND empty string `''`
- Always include `''` as fallback for boxes with broken `get_mac_address()`
- `_get_label_printer()` no longer blocks on empty MAC — uses IP-matched box

---

### 📁 Files Changed in 1.4.0

| File | Change |
|------|--------|
| `__manifest__.py` | Version bump → `18.0.1.4.0` |
| `controllers/iot_patch_controller.py` | **NEW** — Odoo 18 IoT controller runtime patch |
| `controllers/webhook_controller.py` | Added `urllib.request` import, direct pricing calc, card_count flush |
| `models/supertcg_batch.py` | `_rec_name`, empty MAC in `iotIdentifiers`, `_get_label_printer` fix |
| `models/supertcg_batch_card.py` | `_rec_name` added |
| `models/supertcg_batch_log.py` | `_rec_name` added |
| `models/supertcg_pricing_config.py` | Computed `name` field added |
| `CHANGELOG.md` | **NEW** — This file |

---

### 🚀 Production Deployment Notes

1. **Install module** on production Odoo
2. **Install `iot` module** (Odoo Enterprise dependency)
3. **Configure nginx** with `/websocket` proxy (see Issue #3 above)
4. **Set IoT Token** in Settings → IoT
5. **Connect IoT box** to production
6. **Create Scanner Device mapping** (API key → printer)
7. **Restart IoT box** after nginx config is confirmed
8. **Test print** before going live

---

### 🏷️ Known Limitations

- **Windows IoT MAC:** If Windows network interface is fixed to report real MAC, the empty-string fallback in `iotIdentifiers` becomes unnecessary but harmless.
- **Label centering:** ZPL coordinates are calibrated for 1.5" × 0.5" labels @ 203dpi. Adjust `LABEL_W`/`LABEL_H` in `_generate_card_zpl()` if using different label stock.

---

### 📝 Issue Keywords for Search

Search for these strings in the codebase to find all workarounds:
- `HARDCODE-ISSUE-1` — Empty MAC / IP fallback
- `HARDCODE-ISSUE-2` — Odoo 18 `get_json_data()`
- `HARDCODE-ISSUE-3` — Nginx websocket proxy
- `HARDCODE-ISSUE-4` — hw_drivers boot-only websocket start
- `HARDCODE-ISSUE-5` — `_rec_name` missing
- `HARDCODE-ISSUE-6` — Pricing compute webhook
- `HARDCODE-ISSUE-7` — `urllib.request` import
- `HARDCODE-ISSUE-8` — Empty MAC in `iotIdentifiers`
