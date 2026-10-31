/**
 * Subscribify - Subscription Action Handlers
 * Real-time date shift math previews for Pause & Resume workflows.
 */

document.addEventListener('DOMContentLoaded', function () {
    const resumeDateInput = document.getElementById('id_resume_date');
    const resumePreviewBox = document.getElementById('resume_math_preview');
    const pausedDaysCount = document.getElementById('preview_paused_days');
    const previewNewBilling = document.getElementById('preview_new_billing');
    const previewNewExpiry = document.getElementById('preview_new_expiry');

    if (resumeDateInput && window.SUBSCRIBIFY_PAUSE_DATA) {
        const pauseData = window.SUBSCRIBIFY_PAUSE_DATA;
        const pausedAtDate = new Date(pauseData.paused_at);
        const nextBillingDate = pauseData.next_billing_date ? new Date(pauseData.next_billing_date) : null;
        const expiryDate = pauseData.expiry_date ? new Date(pauseData.expiry_date) : null;

        function updateResumeMath() {
            const resumeVal = resumeDateInput.value;
            if (!resumeVal) {
                if (resumePreviewBox) resumePreviewBox.style.display = 'none';
                return;
            }

            const chosenResumeDate = new Date(resumeVal);
            const diffTime = chosenResumeDate - pausedAtDate;
            const diffDays = Math.max(0, Math.ceil(diffTime / (1000 * 60 * 60 * 24)));

            if (diffTime < 0) {
                if (resumePreviewBox) {
                    resumePreviewBox.style.display = 'block';
                    resumePreviewBox.className = 'alert alert-danger';
                    resumePreviewBox.innerHTML = '<i class="bi bi-exclamation-triangle"></i> Resume date cannot be earlier than pause date (' + pauseData.paused_at + ').';
                }
                return;
            }

            if (resumePreviewBox) {
                resumePreviewBox.style.display = 'block';
                resumePreviewBox.className = 'alert alert-info border-info';
            }

            if (pausedDaysCount) pausedDaysCount.textContent = diffDays;

            if (nextBillingDate && previewNewBilling) {
                const newBilling = new Date(nextBillingDate);
                newBilling.setDate(newBilling.getDate() + diffDays);
                previewNewBilling.textContent = newBilling.toISOString().split('T')[0];
            }

            if (expiryDate && previewNewExpiry) {
                const newExpiry = new Date(expiryDate);
                newExpiry.setDate(newExpiry.getDate() + diffDays);
                previewNewExpiry.textContent = newExpiry.toISOString().split('T')[0];
            }
        }

        resumeDateInput.addEventListener('input', updateResumeMath);
        resumeDateInput.addEventListener('change', updateResumeMath);
    }
});
