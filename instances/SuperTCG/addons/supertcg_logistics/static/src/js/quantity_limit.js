document.addEventListener('DOMContentLoaded', function() {
    // Use capture phase to intercept clicks before Odoo's handler runs
    document.addEventListener('click', function(ev) {
        var button = ev.target.closest('.js_add_cart_json');
        if (!button) return;

        // Only intercept + buttons (those containing fa-plus icon)
        var isPlusButton = button.querySelector('.fa-plus') !== null;
        if (!isPlusButton) return; // Allow minus button to work normally

        // Find the quantity container
        var container = button.closest('.css_quantity');
        if (!container) return;

        // Find the visible quantity input
        var input = container.querySelector('input.js_quantity[type="text"]');
        if (!input) return;

        var maxQty = parseInt(input.getAttribute('data-max')) || 0;
        if (maxQty <= 0) return; // No limit set, allow

        var currentQty = parseInt(input.value) || 0;

        if (currentQty >= maxQty) {
            // Prevent Odoo from processing the click
            ev.preventDefault();
            ev.stopPropagation();

            // Flash the input border red to indicate max reached
            input.style.transition = 'border-color 0.2s';
            input.style.borderColor = '#dc3545';
            setTimeout(function() {
                input.style.borderColor = '';
            }, 800);

            return false;
        }
    }, true);
});
