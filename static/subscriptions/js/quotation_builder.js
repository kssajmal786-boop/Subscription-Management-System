/**
 * Subscribify - Interactive Quotation Builder
 * Handles dynamic line item additions, real-time catalog pricing lookups,
 * line subtotal calculations, tax calculations, and discount rules.
 */

document.addEventListener('DOMContentLoaded', function () {
    const linesTableBody = document.getElementById('quotation_lines_tbody');
    const addLineBtn = document.getElementById('btn_add_line');
    const discountCodeInput = document.getElementById('discount_code_input');
    const planSelect = document.getElementById('plan_select');
    
    // Summary elements
    const summarySubtotal = document.getElementById('summary_subtotal');
    const summaryDiscount = document.getElementById('summary_discount');
    const summaryTax = document.getElementById('summary_tax');
    const summaryTotal = document.getElementById('summary_total');
    const discountFeedback = document.getElementById('discount_feedback');

    // Parse product data embedded in template
    const productsData = window.SUBSCRIBIFY_PRODUCTS || {};

    let lineIndex = 0;

    function createRow(productId = '', variantId = '', quantity = 1, customPrice = '') {
        lineIndex++;
        const tr = document.createElement('tr');
        tr.className = 'quotation-line-row';
        tr.id = `line_row_${lineIndex}`;

        let productOptions = '<option value="">-- Select Product --</option>';
        for (const [id, prod] of Object.entries(productsData)) {
            const selected = (id == productId) ? 'selected' : '';
            productOptions += `<option value="${id}" ${selected}>${prod.name} (₹${prod.base_sales_price})</option>`;
        }

        tr.innerHTML = `
            <td>
                <select name="product_id[]" class="form-select product-select" id="product_select_${lineIndex}" required>
                    ${productOptions}
                </select>
            </td>
            <td>
                <select name="variant_id[]" class="form-select variant-select" id="variant_select_${lineIndex}">
                    <option value="">-- Base / No Variant --</option>
                </select>
            </td>
            <td style="width: 110px;">
                <input type="number" name="quantity[]" class="form-control quantity-input" id="quantity_input_${lineIndex}" value="${quantity}" min="1" required>
            </td>
            <td style="width: 140px;">
                <div class="input-group">
                    <span class="input-group-text">₹</span>
                    <input type="number" step="0.01" name="custom_price[]" class="form-control price-input" id="price_input_${lineIndex}" value="${customPrice}" placeholder="Auto">
                </div>
            </td>
            <td style="width: 100px;">
                <span class="tax-rate-display" id="tax_rate_display_${lineIndex}">18.00%</span>
            </td>
            <td class="text-end fw-bold" style="width: 140px;">
                <span class="line-subtotal-display" id="line_subtotal_${lineIndex}">₹0.00</span>
            </td>
            <td class="text-center" style="width: 60px;">
                <button type="button" class="btn btn-outline-danger btn-sm btn-remove-line" id="btn_remove_line_${lineIndex}" title="Remove item">
                    <i class="bi bi-trash"></i> &times;
                </button>
            </td>
        `;

        linesTableBody.appendChild(tr);

        const prodSelectEl = tr.querySelector('.product-select');
        const varSelectEl = tr.querySelector('.variant-select');
        const qtyInputEl = tr.querySelector('.quantity-input');
        const priceInputEl = tr.querySelector('.price-input');
        const removeBtnEl = tr.querySelector('.btn-remove-line');

        // Update variants dropdown on product select
        function updateVariants() {
            const selectedProdId = prodSelectEl.value;
            varSelectEl.innerHTML = '<option value="">-- Base / No Variant --</option>';

            if (selectedProdId && productsData[selectedProdId]) {
                const prod = productsData[selectedProdId];
                tr.querySelector('.tax-rate-display').textContent = `${prod.tax_rate}%`;

                if (prod.variants && prod.variants.length > 0) {
                    prod.variants.forEach(v => {
                        const isSel = (v.variant_id == variantId) ? 'selected' : '';
                        varSelectEl.innerHTML += `<option value="${v.variant_id}" data-add-price="${v.additional_price}" data-eff-price="${v.effective_price}" ${isSel}>
                            ${v.attribute_value} (+₹${v.additional_price}) [₹${v.effective_price}]
                        </option>`;
                    });
                }

                // If no custom price entered, auto-fill effective price
                updatePriceField();
            } else {
                tr.querySelector('.tax-rate-display').textContent = '0.00%';
                priceInputEl.value = '';
            }
            recalculateTotals();
        }

        function updatePriceField() {
            const selectedProdId = prodSelectEl.value;
            if (!selectedProdId || !productsData[selectedProdId]) return;
            const prod = productsData[selectedProdId];

            let effPrice = parseFloat(prod.base_sales_price);
            const selectedVariantOpt = varSelectEl.selectedOptions[0];
            if (selectedVariantOpt && selectedVariantOpt.dataset.effPrice) {
                effPrice = parseFloat(selectedVariantOpt.dataset.effPrice);
            }

            if (!priceInputEl.dataset.userEdited) {
                priceInputEl.value = effPrice.toFixed(2);
            }
        }

        prodSelectEl.addEventListener('change', function () {
            priceInputEl.dataset.userEdited = '';
            updateVariants();
        });

        varSelectEl.addEventListener('change', function () {
            priceInputEl.dataset.userEdited = '';
            updatePriceField();
            recalculateTotals();
        });

        priceInputEl.addEventListener('input', function () {
            priceInputEl.dataset.userEdited = 'true';
            recalculateTotals();
        });

        qtyInputEl.addEventListener('input', recalculateTotals);

        removeBtnEl.addEventListener('click', function () {
            if (linesTableBody.querySelectorAll('tr').length > 1) {
                tr.remove();
                recalculateTotals();
            } else {
                alert('A quotation must have at least one line item.');
            }
        });

        if (productId) {
            updateVariants();
        }
    }

    function recalculateTotals() {
        let subtotal = 0;
        let totalTax = 0;
        let totalQuantity = 0;

        const rows = linesTableBody.querySelectorAll('.quotation-line-row');
        rows.forEach(row => {
            const prodSelect = row.querySelector('.product-select');
            const qtyInput = row.querySelector('.quantity-input');
            const priceInput = row.querySelector('.price-input');
            const subtotalDisplay = row.querySelector('.line-subtotal-display');

            const prodId = prodSelect.value;
            const qty = parseInt(qtyInput.value) || 0;
            const price = parseFloat(priceInput.value) || 0;

            const lineSub = qty * price;
            subtotal += lineSub;
            totalQuantity += qty;

            let taxRate = 18.0;
            if (prodId && productsData[prodId]) {
                taxRate = parseFloat(productsData[prodId].tax_rate);
            }
            const lineTax = (lineSub * taxRate) / 100.0;
            totalTax += lineTax;

            subtotalDisplay.textContent = `₹${lineSub.toFixed(2)}`;
        });

        // Discount calculation
        let discountAmount = 0;
        const discountCode = (discountCodeInput ? discountCodeInput.value.trim().toUpperCase() : '');
        const discountRules = window.SUBSCRIBIFY_DISCOUNTS || {};

        if (discountFeedback) discountFeedback.textContent = '';

        if (discountCode && discountRules[discountCode]) {
            const rule = discountRules[discountCode];
            let isValid = true;
            let errMsg = '';

            if (subtotal < parseFloat(rule.min_purchase_amount)) {
                isValid = false;
                errMsg = `Minimum subtotal of ₹${rule.min_purchase_amount} required.`;
            } else if (totalQuantity < parseInt(rule.min_quantity)) {
                isValid = false;
                errMsg = `Minimum quantity of ${rule.min_quantity} items required.`;
            }

            if (isValid) {
                if (rule.discount_type === 'Percentage') {
                    discountAmount = (subtotal * parseFloat(rule.discount_value)) / 100.0;
                } else {
                    discountAmount = Math.min(parseFloat(rule.discount_value), subtotal);
                }
                if (discountFeedback) {
                    discountFeedback.innerHTML = `<span class="text-success"><i class="bi bi-check-circle"></i> Applied: ${rule.name} (-₹${discountAmount.toFixed(2)})</span>`;
                }
            } else if (discountFeedback) {
                discountFeedback.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle"></i> ${errMsg}</span>`;
            }
        } else if (discountCode && discountFeedback) {
            discountFeedback.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle"></i> Invalid discount code</span>`;
        }

        const grandTotal = Math.max(0, subtotal - discountAmount) + totalTax;

        if (summarySubtotal) summarySubtotal.textContent = `₹${subtotal.toFixed(2)}`;
        if (summaryDiscount) summaryDiscount.textContent = `-₹${discountAmount.toFixed(2)}`;
        if (summaryTax) summaryTax.textContent = `+₹${totalTax.toFixed(2)}`;
        if (summaryTotal) summaryTotal.textContent = `₹${grandTotal.toFixed(2)}`;
    }

    if (addLineBtn) {
        addLineBtn.addEventListener('click', function () {
            createRow();
        });
    }

    if (discountCodeInput) {
        discountCodeInput.addEventListener('input', recalculateTotals);
    }

    // Auto-select product on plan change if plan links a specific product/variant
    if (planSelect) {
        planSelect.addEventListener('change', function () {
            const selectedOpt = planSelect.selectedOptions[0];
            if (selectedOpt && selectedOpt.dataset.productId) {
                const pId = selectedOpt.dataset.productId;
                const vId = selectedOpt.dataset.variantId || '';
                // If first row is empty, populate it
                const firstRow = linesTableBody.querySelector('.quotation-line-row');
                if (firstRow) {
                    const sel = firstRow.querySelector('.product-select');
                    if (!sel.value) {
                        sel.value = pId;
                        sel.dispatchEvent(new Event('change'));
                        if (vId) {
                            setTimeout(() => {
                                const vSel = firstRow.querySelector('.variant-select');
                                vSel.value = vId;
                                vSel.dispatchEvent(new Event('change'));
                            }, 50);
                        }
                    }
                }
            }
        });
    }

    // Initialize with 1 default row if table is empty
    if (linesTableBody && linesTableBody.children.length === 0) {
        createRow();
    }
});
