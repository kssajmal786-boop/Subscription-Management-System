"""
payments package – Re-export canonical Payment model from billing.models
"""
from billing.models import Payment

__all__ = ["Payment"]
