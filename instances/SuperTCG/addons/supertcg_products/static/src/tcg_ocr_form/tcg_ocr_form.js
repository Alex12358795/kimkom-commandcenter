/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { browser } from "@web/core/browser/browser";

const DRAFT_KEY = "tcg_ocr_draft_form";
const RECENT_CATEG_KEY = "tcg_recent_categories";

export class TcgOcrCardForm extends Component {
    static template = "supertcg_products.TcgOcrCardForm";

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
            isProcessingOcr: false,
            ocrText: "",
            priceSuggestions: [],
            selectedSuggestion: null,
            sessionProducts: [],
            sessionCount: 0,
            toast: null,
            errors: {},
            showSessionSummary: false,
            taxWarning: "",
            priceWarning: "",
            categPreselected: false,
            locationPreselected: false,
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
            if (!draft.name && !draft.listPrice && !(draft.photos && draft.photos.length)) return false;
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

    _validate() {
        const errors = {};
        if (!this.state.name.trim()) {
            errors.name = "Name is required";
        }
        if (!this.state.listPrice || parseFloat(this.state.listPrice) < 0) {
            errors.listPrice = "Valid sales price is required";
        }
        // Cost is required but kept empty for manual entry
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

    async _processOcr(imageBase64) {
        this.state.isProcessingOcr = true;
        this.state.ocrText = "";
        this.state.priceSuggestions = [];
        this.state.selectedSuggestion = null;

        try {
            console.log('OCR: Starting text extraction, image length:', imageBase64 ? imageBase64.length : 0);
            const ocrResult = await rpc("/tcg/ocr_extract", { image: imageBase64 });
            console.log('OCR: Raw result:', ocrResult);
            
            if (!ocrResult.success) {
                console.log('OCR: OCR failed:', ocrResult.error);
                this._showToast("OCR failed: " + (ocrResult.error || "Unknown error"), "error");
                return;
            }
            
            if (!ocrResult.text || !ocrResult.text.trim()) {
                console.log('OCR: No text detected in image');
                this._showToast("No text detected. Please enter manually.", "error");
                return;
            }
            
            // Got text successfully - OCR service already returns largest text by bounding box area
            this.state.ocrText = ocrResult.text;
            console.log('OCR: Detected text (largest by bounding box):', ocrResult.text.substring(0, 100));
            
            // Use OCR text directly as name (it's already the largest/boldest text)
            const searchTerm = ocrResult.text.split('\n')[0].trim();
            this.state.name = searchTerm;
            console.log('OCR: Calling price lookup for:', searchTerm);
            
            const priceResult = await rpc("/tcg/search_card_price", { term: searchTerm });
            console.log('OCR: Price lookup result:', priceResult);
            
            if (priceResult.success && priceResult.cards && priceResult.cards.length > 0) {
                this.state.priceSuggestions = priceResult.cards;
                const best = priceResult.cards[0];
                this.state.selectedSuggestion = best;
                    if (best.price_eur) {
                        this.state.listPrice = String(best.price_eur);
                        console.log('OCR: Set sales price to €', best.price_eur);
                    }
                this._updatePriceWarning();
                this._showToast("Card recognized! Review and adjust.", "success");
            } else {
                console.log('OCR: No price suggestions found. Error:', priceResult.error);
                this._showToast("Card recognized but no prices found. Enter manually.", "error");
            }
            
        } catch (e) {
            console.error('OCR: Process error:', e);
            this._showToast("OCR failed. Please enter manually.", "error");
        } finally {
            this.state.isProcessingOcr = false;
            this._scheduleDraftSave();
        }
    }

    async onSelectSuggestion(suggestion) {
        this.state.selectedSuggestion = suggestion;
        this.state.name = suggestion.name;
        if (suggestion.price_eur) {
            this.state.listPrice = String(suggestion.price_eur);
        }
        this._updatePriceWarning();
        this._scheduleDraftSave();
    }

    async onReSearchPrice() {
        const searchTerm = this.state.name.trim();
        if (!searchTerm) {
            this._showToast("Enter a name first", "error");
            return;
        }

        this.state.isProcessingOcr = true;
        this.state.priceSuggestions = [];
        this.state.selectedSuggestion = null;

        try {
            console.log('OCR: Re-searching prices for:', searchTerm);

            const priceResult = await rpc("/tcg/search_card_price", { term: searchTerm });
            console.log('OCR: Re-search result:', priceResult);

            if (priceResult.success && priceResult.cards && priceResult.cards.length > 0) {
                this.state.priceSuggestions = priceResult.cards;
                const best = priceResult.cards[0];
                this.state.selectedSuggestion = best;
                if (best.price_eur) {
                    this.state.listPrice = String(best.price_eur);
                    console.log('OCR: Set sales price to €', best.price_eur);
                }
                this._updatePriceWarning();
                this._showToast(`Found ${priceResult.cards.length} cards`, "success");
            } else {
                this._showToast(priceResult.error || "No cards found", "error");
            }
        } catch (e) {
            console.error('OCR: Re-search error:', e);
            this._showToast("Price lookup failed", "error");
        } finally {
            this.state.isProcessingOcr = false;
            this._scheduleDraftSave();
        }
    }

    async _submitProduct() {
        if (!this._validate()) {
            return false;
        }
        this.state.isSaving = true;

        try {
            const photos = this.state.photos.map(p => p.base64);
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
                this.state.ocrText = "";
                this.state.priceSuggestions = [];
                this.state.selectedSuggestion = null;
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
        this.state.ocrText = "";
        this.state.priceSuggestions = [];
        this.state.selectedSuggestion = null;
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
        const file = files[0];
        const reader = new FileReader();
        reader.onload = function(e) {
            const full = e.target.result;
            const base64 = full.split(",")[1];
            self.state.photos = [{
                id: Date.now() + Math.random(),
                base64: base64,
                preview: full,
            }];
            self._processOcr(base64);
        };
        reader.onerror = function() {
            console.error('TCG OCR: FileReader error');
        };
        reader.readAsDataURL(file);
        ev.target.value = "";
    }

    removePhoto(photoId) {
        this.state.photos = this.state.photos.filter(p => p.id !== photoId);
        this.state.ocrText = "";
        this.state.priceSuggestions = [];
        this.state.selectedSuggestion = null;
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

    onNameInput(ev) {
        this.state.name = ev.target.value;
        if (this.state.errors.name) delete this.state.errors.name;
        this._scheduleDraftSave();
    }
}

registry.category("actions").add("tcg_ocr_card_form", TcgOcrCardForm);

export default TcgOcrCardForm;