/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { browser } from "@web/core/browser/browser";

const DRAFT_KEY = "tcg_draft_form";
const RECENT_CATEG_KEY = "tcg_recent_categories";

export class TcgCardForm extends Component {
    static template = "supertcg_products.TcgCardForm";

    setup() {
        this.state = useState({
            name: "",
            listPrice: "",
            standardPrice: "",
            categId: null,
            locationId: null,
            taxesId: [],
            supplierTaxesId: [],
            onHandQty: 1,
            photos: [],
            categories: [],
            defaultTaxes: {},
            isSaving: false,
            sessionProducts: [],
            sessionCount: 0,
            toast: null,
            errors: {},
            showSessionSummary: false,
            taxWarning: "",
            priceWarning: "",
            categPreselected: false,
            locationPreselected: false,
            productSearchResults: [],
            productSearchOpen: false,
            selectedProductId: null,
            consignmentMode: false,
            consignmentPartnerId: null,
            consignmentPartnerName: "",
            employeeId: null,
            employeeName: "",
            linkedPoId: null,
            condition: "NM",
        });

        this.nameRef = useRef("nameInput");
        this.toastTimer = null;
        this.searchTimer = null;
        this.draftTimer = null;

        onWillStart(async () => {
            await this._loadInitialData();
        });

        onWillUnmount(() => {
            if (this.toastTimer) clearTimeout(this.toastTimer);
            if (this.searchTimer) clearTimeout(this.searchTimer);
            if (this.draftTimer) clearTimeout(this.draftTimer);
        });
    }

    _getUrlParam(name) {
        const url = new URL(browser.location.href);
        const param = url.searchParams.get(name);
        if (param) return param;
        const hash = url.hash;
        const match = hash.match(new RegExp(name + "=([^&]+)"));
        return match ? decodeURIComponent(match[1]) : null;
    }

    _saveRecentCategory(categId) {
        if (!categId) return;
        try {
            let ids = JSON.parse(localStorage.getItem(RECENT_CATEG_KEY) || "[]");
            ids = ids.filter(id => id !== categId);
            ids.unshift(categId);
            ids = ids.slice(0, 5);
            localStorage.setItem(RECENT_CATEG_KEY, JSON.stringify(ids));
        } catch (e) {}
    }

    _reorderCategories(categories) {
        try {
            const recentIds = JSON.parse(localStorage.getItem(RECENT_CATEG_KEY) || "[]");
            if (!recentIds.length) return categories;
            const recent = [];
            const rest = [];
            for (const cat of categories) {
                if (recentIds.includes(cat.id)) {
                    recent.push(cat);
                } else {
                    rest.push(cat);
                }
            }
            recent.sort((a, b) => recentIds.indexOf(a.id) - recentIds.indexOf(b.id));
            return [...recent, ...rest];
        } catch (e) {
            return categories;
        }
    }

    _saveDraft() {
        try {
            const draft = {
                name: this.state.name,
                listPrice: this.state.listPrice,
                standardPrice: this.state.standardPrice,
                categId: this.state.categId,
                condition: this.state.condition,
                onHandQty: this.state.onHandQty,
                taxesId: this.state.taxesId,
                supplierTaxesId: this.state.supplierTaxesId,
                photos: this.state.photos.map(p => ({ id: p.id, base64: p.base64, preview: p.preview })),
                locationId: this.state.locationId,
            };
            localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
        } catch (e) {}
    }

    _restoreDraft() {
        try {
            const raw = localStorage.getItem(DRAFT_KEY);
            if (!raw) return false;
            const draft = JSON.parse(raw);
            if (!draft.name && !draft.listPrice && !draft.photos.length) return false;
            this.state.name = draft.name || "";
            this.state.listPrice = draft.listPrice || "";
            this.state.standardPrice = draft.standardPrice || "";
            if (draft.categId && !this.state.categPreselected) {
                this.state.categId = draft.categId;
            }
            if (draft.condition) {
                this.state.condition = draft.condition;
            }
            if (draft.onHandQty !== undefined) {
                this.state.onHandQty = draft.onHandQty;
            }
            if (draft.locationId && !this.state.locationPreselected) {
                this.state.locationId = draft.locationId;
            }
            if (draft.photos && draft.photos.length) {
                this.state.photos = draft.photos;
            }
            this._updatePriceWarning();
            this._showToast("Draft restored", "success");
            return true;
        } catch (e) {
            return false;
        }
    }

    _clearDraft() {
        try {
            localStorage.removeItem(DRAFT_KEY);
        } catch (e) {}
    }

    _scheduleDraftSave() {
        if (this.draftTimer) clearTimeout(this.draftTimer);
        this.draftTimer = setTimeout(() => this._saveDraft(), 500);
    }

    _updatePriceWarning() {
        const lp = parseFloat(this.state.listPrice);
        const sp = parseFloat(this.state.standardPrice);
        if (lp && sp && lp < sp) {
            this.state.priceWarning = "Sales price is lower than cost price. Is this correct?";
        } else {
            this.state.priceWarning = "";
        }
    }

    async _loadInitialData() {
        try {
            const [categories, taxes] = await Promise.all([
                rpc("/tcg/get_categories"),
                rpc("/tcg/get_default_taxes"),
            ]);
            this.state.categories = this._reorderCategories(categories);
            this.state.defaultTaxes = taxes;

            if (taxes.sale_tax_id) {
                this.state.taxesId = [taxes.sale_tax_id];
            }
            if (taxes.purchase_tax_id) {
                this.state.supplierTaxesId = [taxes.purchase_tax_id];
            }

            const initialCateg = this._getUrlParam("categ_id");
            if (initialCateg) {
                this.state.categId = parseInt(initialCateg);
                this.state.categPreselected = true;
            }

            const initialLocation = this._getUrlParam("location_id");
            if (initialLocation) {
                this.state.locationId = parseInt(initialLocation);
                this.state.locationPreselected = true;
            }

            const consignmentMode = this._getUrlParam("consignment_mode");
            if (consignmentMode === "1") {
                this.state.consignmentMode = true;
                this.state.consignmentPartnerId = parseInt(this._getUrlParam("consignment_partner_id"));
                this.state.consignmentPartnerName = decodeURIComponent(this._getUrlParam("consignment_partner_name") || "");
            }

            const employeeId = this._getUrlParam("employee_id");
            if (employeeId) {
                this.state.employeeId = parseInt(employeeId);
                this.state.employeeName = decodeURIComponent(this._getUrlParam("employee_name") || "");
            }

            const poId = this._getUrlParam("po_id");
            if (poId) {
                this.state.linkedPoId = parseInt(poId);
            }

            const warnings = [];
            if (!taxes.sale_tax_found) {
                warnings.push("Customer tax 'Margeverkoop met kostprijs' not found");
            }
            if (!taxes.purchase_tax_found) {
                warnings.push("Vendor tax 'Margeinkoop' not found");
            }
            if (warnings.length) {
                this.state.taxWarning = warnings.join(". ") + ". Products will be created without default taxes.";
            }

            if (!this.state.categPreselected && !this.state.consignmentMode) {
                this._restoreDraft();
            }
        } catch (e) {
            this._showToast("Failed to load form data", "error");
        }
    }

    _showToast(message, type = "success") {
        this.state.toast = { message, type };
        if (this.toastTimer) clearTimeout(this.toastTimer);
        this.toastTimer = setTimeout(() => {
            this.state.toast = null;
        }, 2500);
    }

    onNameInput(ev) {
        this.state.selectedProductId = null;
        if (this.state.errors.name) delete this.state.errors.name;
        if (this.searchTimer) clearTimeout(this.searchTimer);
        this._scheduleDraftSave();
        const term = ev.target.value.trim();
        if (term.length < 2) {
            this.state.productSearchResults = [];
            this.state.productSearchOpen = false;
            return;
        }
        this.searchTimer = setTimeout(async () => {
            try {
                const results = await rpc("/tcg/search_product", { term });
                this.state.productSearchResults = results;
                this.state.productSearchOpen = results.length > 0;
            } catch (e) {
                this.state.productSearchResults = [];
                this.state.productSearchOpen = false;
            }
        }, 300);
    }

    onNameBlur() {
        setTimeout(() => {
            this.state.productSearchOpen = false;
        }, 200);
    }

    async onSelectProduct(productId) {
        this.state.productSearchOpen = false;
        this.state.productSearchResults = [];
        try {
            const result = await rpc("/tcg/get_product", { product_id: productId });
            if (result.success) {
                const p = result.result;
                this.state.selectedProductId = p.id;
                this.state.name = p.name;
                this.state.listPrice = String(p.list_price);
                this.state.standardPrice = String(p.standard_price);
                if (p.categ_id) {
                    this.state.categId = p.categ_id;
                    this.state.categPreselected = false;
                }
                if (p.taxes_id && p.taxes_id.length) {
                    this.state.taxesId = p.taxes_id;
                }
                if (p.supplier_taxes_id && p.supplier_taxes_id.length) {
                    this.state.supplierTaxesId = p.supplier_taxes_id;
                }
                this.state.onHandQty = p.on_hand_qty || 1;
                if (p.image_url) {
                    this.state.photos = [];
                }
                this._updatePriceWarning();
                this._showToast("Loaded: " + p.name);
            }
        } catch (e) {
            this._showToast("Failed to load product", "error");
        }
    }

    _validate() {
        const errors = {};
        if (!this.state.name.trim()) {
            errors.name = "Name is required";
        }
        if (!this.state.listPrice || parseFloat(this.state.listPrice) < 0) {
            errors.listPrice = "Valid sales price is required";
        }
        if (!this.state.standardPrice || parseFloat(this.state.standardPrice) < 0) {
            errors.standardPrice = "Valid cost is required";
        }
        if (!this.state.categId) {
            errors.categId = "Category is required";
        }
        this.state.errors = errors;
        return Object.keys(errors).length === 0;
    }

    _openPrintWindow(url) {
        const printWindow = window.open("", "_blank");
        if (printWindow) {
            printWindow.location.href = url;
        } else {
            this._showToast("Pop-up blocked. Please allow pop-ups for this site.", "error");
        }
    }

    _goToDashboard() {
        this._clearDraft();
        browser.location.href = "/tcg";
    }

    async _submitProduct() {
        if (!this._validate()) {
            return false;
        }
        this.state.isSaving = true;

        try {
            const photos = this.state.photos.map(p => p.base64);
            if (this.state.selectedProductId) {
                const product = await rpc("/tcg/get_product", { product_id: this.state.selectedProductId });
                this.state.sessionProducts.push({
                    id: this.state.selectedProductId,
                    name: this.state.name.trim() + " [" + this.state.condition + "]",
                    barcode: product.result ? product.result.barcode : "",
                });
                this.state.sessionCount += 1;
                this._showToast(this.state.name.trim() + " [" + this.state.condition + "] added to session");
                return { product_id: this.state.selectedProductId, product_name: this.state.name.trim() + " [" + this.state.condition + "]" };
            }
            const rpcData = {
                name: this.state.name.trim() + " [" + this.state.condition + "]",
                list_price: this.state.listPrice,
                standard_price: this.state.standardPrice,
                categ_id: this.state.categId,
                location_id: this.state.locationId,
                taxes_id: this.state.taxesId,
                supplier_taxes_id: this.state.supplierTaxesId,
                on_hand_qty: parseInt(this.state.onHandQty) || 1,
                photos: photos,
            };
            let route = "/tcg/create_product";
            if (this.state.consignmentMode) {
                route = "/tcg/create_consignment_product";
                rpcData.partner_id = this.state.consignmentPartnerId;
            }
            if (this.state.employeeId) {
                rpcData.employee_id = this.state.employeeId;
            }
            if (!this.state.consignmentMode && this.state.linkedPoId) {
                rpcData.po_id = this.state.linkedPoId;
            }
            const result = await rpc(route, rpcData);

            if (result.success) {
                this._saveRecentCategory(this.state.categId);
                this._clearDraft();
                this.state.sessionProducts.push({
                    id: result.result.product_id,
                    name: result.result.product_name,
                    barcode: result.result.barcode,
                });
                this.state.sessionCount += 1;
                this._showToast(result.result.product_name + " saved");
                return result.result;
            } else {
                this._showToast(result.error || "Failed to create product", "error");
                return false;
            }
        } catch (e) {
            this._showToast("Network error. Please try again.", "error");
            return false;
        } finally {
            this.state.isSaving = false;
        }
    }

    async onSaveAndAddAnother() {
        const result = await this._submitProduct();
        if (result) {
            this._openPrintWindow("/tcg/print_label/" + result.product_id);
            this._resetForm(true);
        }
    }

    async onFinishSession() {
        if (this.state.name.trim()) {
            await this._submitProduct();
        }
        if (this.state.sessionProducts.length === 0) {
            this._goToDashboard();
            return;
        }
        this.state.showSessionSummary = true;
    }

    async onPrintAllLabels() {
        const productIds = this.state.sessionProducts.map(p => p.id);
        try {
            const result = await rpc("/tcg/batch_print_labels", {
                product_ids: productIds,
            });
            if (result.success && result.report_url) {
                this._openPrintWindow(result.report_url);
            } else {
                this._showToast(result.error || "Failed to generate labels", "error");
            }
        } catch (e) {
            this._showToast("Failed to generate batch labels", "error");
        }
    }

    onCloseSession() {
        this._goToDashboard();
    }

    onGoBack() {
        this._goToDashboard();
    }

    _resetForm(keepBulkFields) {
        this.state.name = "";
        this.state.listPrice = "";
        this.state.standardPrice = "";
        this.state.photos = [];
        this.state.errors = {};
        this.state.condition = "NM";
        this.state.priceWarning = "";
        if (!keepBulkFields) {
            this.state.categId = null;
            this.state.categPreselected = false;
            this.state.locationId = null;
            this.state.locationPreselected = false;
            this.state.taxesId = this.state.defaultTaxes.sale_tax_id
                ? [this.state.defaultTaxes.sale_tax_id] : [];
            this.state.supplierTaxesId = this.state.defaultTaxes.purchase_tax_id
                ? [this.state.defaultTaxes.purchase_tax_id] : [];
            this.state.onHandQty = 1;
        }
        setTimeout(() => {
            if (this.nameRef.el) {
                this.nameRef.el.focus();
            }
        }, 150);
    }

    onFileUpload(ev) {
        const files = ev.target.files;
        if (!files || !files.length) return;
        const self = this;
        Array.from(files).forEach(file => {
            const reader = new FileReader();
            reader.onload = function(e) {
                const full = e.target.result;
                const base64 = full.split(",")[1];
                self.state.photos.push({
                    id: Date.now() + Math.random(),
                    base64: base64,
                    preview: full,
                });
                self._scheduleDraftSave();
            };
            reader.onerror = function() {
                console.error('TCG: FileReader error');
            };
            reader.readAsDataURL(file);
        });
        ev.target.value = "";
    }

    removePhoto(photoId) {
        this.state.photos = this.state.photos.filter(p => p.id !== photoId);
        this._scheduleDraftSave();
    }

    onCategChange(ev) {
        const val = ev.target.value;
        this.state.categId = val ? parseInt(val) : null;
        if (this.state.errors.categId) delete this.state.errors.categId;
        this._scheduleDraftSave();
    }

    onPriceInput() {
        this._updatePriceWarning();
        this._scheduleDraftSave();
    }

    onFieldInput(fieldName, ev) {
        this.state[fieldName] = ev.target.value;
        if (this.state.errors[fieldName]) delete this.state.errors[fieldName];
        this._scheduleDraftSave();
        if (fieldName === "listPrice" || fieldName === "standardPrice") {
            this._updatePriceWarning();
        }
    }

    onQtyChange() {
        this._scheduleDraftSave();
    }

    onConditionChange(code) {
        this.state.condition = code;
        this._scheduleDraftSave();
    }
}

registry.category("actions").add("tcg_card_form", TcgCardForm);

export default TcgCardForm;
