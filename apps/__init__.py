"""
apps package – Compatibility shims for legacy modular imports
"""
import sys
import accounts
import catalog
import subscriptions
import billing
import payments
import notifications

# Map apps.X to top-level X modules
sys.modules['apps.accounts'] = accounts
sys.modules['apps.catalog'] = catalog
sys.modules['apps.subscriptions'] = subscriptions
sys.modules['apps.billing'] = billing
sys.modules['apps.payments'] = payments
sys.modules['apps.notifications'] = notifications
