class StockScannerError(Exception):
    """Base exception for the application."""


class DataProviderError(StockScannerError):
    """Raised when the market data provider fails."""


class DataNotAvailableError(StockScannerError):
    """Raised when requested data does not exist."""


class InsufficientDataError(StockScannerError):
    """Raised when there is not enough history to compute indicators."""


class ScanJobNotFoundError(StockScannerError):
    """Raised when a scan job cannot be found."""


class DuplicateScanJobError(StockScannerError):
    """Raised when a scan job for the date already exists."""
