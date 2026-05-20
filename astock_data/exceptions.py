"""Custom exception hierarchy for astock_data."""


class AStockError(Exception):
    """Base exception for all astock_data errors."""
    pass


class DataSourceError(AStockError):
    """Raised when a data source fails to return valid data."""
    pass


class MootdxError(DataSourceError):
    """mootdx TCP connection/protocol errors."""
    pass


class AKShareError(DataSourceError):
    """akshare wrapper errors."""
    pass


class TencentFinanceError(DataSourceError):
    """Tencent Finance API errors."""
    pass


class CLSError(DataSourceError):
    """财联社 API errors."""
    pass


class THSError(DataSourceError):
    """同花顺 API errors."""
    pass


class IWencaiError(DataSourceError):
    """iwencai API errors (auth, rate-limit, etc.)."""
    pass


class RateLimitError(AStockError):
    """Raised when rate limiter blocks a request."""
    pass


class CacheError(AStockError):
    """Cache backend errors."""
    pass


class ConfigError(AStockError):
    """Configuration errors (missing keys, invalid paths)."""
    pass


class ValidationError(AStockError):
    """Input validation errors (bad stock code, date range)."""
    pass
