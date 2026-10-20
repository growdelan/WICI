"""Only the four PRD sources; no implicit fallback providers."""
from .base import FetchResult
from .html import RCBAdapter, SGAdapter
from .imgw import IMGWPDFAdapter
from .rso import RSOAdapter

ADAPTERS = {adapter.source_id: adapter for adapter in (IMGWPDFAdapter(), RSOAdapter(), RCBAdapter(), SGAdapter())}
__all__ = ['ADAPTERS', 'FetchResult', 'IMGWPDFAdapter', 'RCBAdapter', 'RSOAdapter', 'SGAdapter']
