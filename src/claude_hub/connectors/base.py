"""Base connector interface and data types for the connector system (R7).

Defines the abstract base class that all connectors implement, along with
the data types used across the connector interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class ConnectorError(Exception):
    """Raised when a connector operation fails.

    Attributes:
        retriable: Whether the operation can be retried.
    """

    def __init__(self, message: str, retriable: bool = False):
        super().__init__(message)
        self.retriable = retriable


@dataclass
class ConnectorResult:
    """A search result from a connector."""

    content: str
    source: str  # Path/URI within the connector
    score: float  # Similarity score, 0-1
    metadata: dict = field(default_factory=dict)
    connector_name: str = ""


@dataclass
class ConnectorItem:
    """A single item in a connector's domain."""

    id: str
    title: str
    content: str
    path: str  # Path/URI within the connector
    metadata: dict = field(default_factory=dict)


@dataclass
class IndexReport:
    """Result of an indexing operation."""

    items_scanned: int = 0
    items_indexed: int = 0
    items_skipped: int = 0
    items_deleted: int = 0
    errors: list[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Interface that all connectors implement."""

    @property
    @abstractmethod
    def connector_type(self) -> str:
        """Return the connector type identifier."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the connector instance name."""

    @abstractmethod
    async def query(
        self, query: str, filters: dict | None = None, limit: int = 10
    ) -> list[ConnectorResult]:
        """Semantic search within this connector's domain.

        Args:
            query: Natural-language search query
            filters: Connector-specific filters (type, date range, etc.)
            limit: Max results to return

        Returns:
            List of results ranked by relevance
        """

    @abstractmethod
    async def list(
        self, path: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[ConnectorItem]:
        """List items in this connector's domain.

        Args:
            path: Sub-path to list within (None = root)
            limit: Max items to return
            offset: Pagination offset

        Returns:
            List of items
        """

    @abstractmethod
    async def get(self, item_id: str) -> ConnectorItem:
        """Get a specific item by ID.

        Args:
            item_id: Item identifier (format is connector-specific)

        Returns:
            The item

        Raises:
            KeyError: Item not found
        """

    # Auth contract — connectors manage their own credentials.
    # Credentials are stored in the connector's `config` JSONB, not in code.
    # Connectors that access external services must:
    # 1. Validate credentials on registration (fail fast if invalid)
    # 2. Handle credential expiry gracefully (return ConnectorError, not crash)
    # 3. Never log or expose credentials in error messages

    async def validate(self) -> bool:
        """Validate connector configuration and credentials.

        Called on registration. Return True if ready, raise
        ConnectorError with details if not.
        """
        return True

    # Optional methods — override if supported

    async def index(self, path: str | None = None) -> IndexReport:
        """Pre-index content for faster retrieval.

        Not all connectors support indexing. Those that don't raise
        NotImplementedError; the registry skips them during index operations.
        """
        raise NotImplementedError(
            f"{self.connector_type} connector does not support indexing"
        )

    async def write(self, item_id: str, content: str) -> bool:
        """Write back to the data source.

        Not all connectors support write-back. Those that don't raise
        NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.connector_type} connector does not support writes"
        )
