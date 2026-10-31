"""
notifications package – Re-export canonical Notification model from billing.models
"""
from billing.models import Notification

__all__ = ["Notification"]
