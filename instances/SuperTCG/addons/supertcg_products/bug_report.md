# QA Bug Report - SuperTCG Odoo Module

**Environment:** odoo-dev-odoo18-dev-1 (dev.supertcg.be)
**Tester:** Antigravity (AI Assistant)
**Date:** 2026-04-11

## 1. Functional Issues

### [BUG-001] Flaky Partner Autocomplete in Consignment Flow
- **Description:** Searching for a partner (e.g., 'Azure') in the consignment dashboard often fails to return results or the dropdown doesn't appear promptly. The subagent had to retry multiple times.
- **Root Cause:** Likely a race condition in the keyup event listener or a slow RPC response for /tcg/aankoop/search_partner.
- **Recommendation:** Implement a debounce for the search input and add a loading indicator.

### [BUG-002] Potential 404 on Product Creation (Verification Required)
- **Description:** The browser subagent reported a 404 error when attempting to save a product from the Card Form.
- **Details:** The reported URL was /tcg/card-entry/stock.
- **Analysis:** This route does NOT exist in the current codebase (controllers/main.py). The code uses /tcg/create_product.
- **Possibility:** Either the subagent misread the console, or there is a leftover piece of JS in the environment pointing to a legacy route that hasn't been updated.
- **Verification:** Check if any old JS files exist in the container or if the OWL component is being loaded from a cached/stale version.

### [BUG-003] Missing Employee/Partner Selection Persistence
- **Description:** In the " Buy-in\ flow, if a form validation error occurs, some selections might be lost or the UX becomes confusing.
- **Recommendation:** Ensure all fields are preserved on error.

## 2. Server-Side Tracebacks
- **Status:** No Python tracebacks were found in the odoo-dev logs during testing.
- **Observation:** Persistent collation version mismatch warnings for the postgres database were noted (expected but should be addressed for production stability).

## 3. Recommended Fixes (Immediate)

### Fix for [BUG-001] - Debounce & Loading
Update static/src/tcg_card_form/tcg_card_form.js or the dashboard JS to include a proper debounce. (Wait, the dashboard logic is in the XML template).

### Verification of Product Creation
I will perform a targeted check of the create_tcg_product method to ensure it doesn't fail on missing keys.

---
**Status:** Q&A ongoing. Product creation flow requires manual verification if possible.
