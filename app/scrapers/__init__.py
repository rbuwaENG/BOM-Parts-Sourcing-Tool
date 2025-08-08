from .base import SupplierScraper, SupplierResult
from .auto import AutoDetectScraper
from .troniclk import TronicLkScraper
from .lscs import LscsScraper
from .mouser import MouserScraper

__all__ = [
    "SupplierScraper",
    "SupplierResult",
    "AutoDetectScraper",
    "TronicLkScraper",
    "LscsScraper",
    "MouserScraper",
]