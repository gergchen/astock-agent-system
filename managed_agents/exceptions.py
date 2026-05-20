class ManagedAgentError(Exception):
    """Base exception for all managed_agents errors."""


class AgentNotFoundError(ManagedAgentError):
    """Agent definition not found in registry."""


class SessionNotFoundError(ManagedAgentError):
    """Session not found in store."""


class SessionExpiredError(ManagedAgentError):
    """Session TTL expired."""


class CompactionError(ManagedAgentError):
    """Compaction pipeline failure."""


class SkillNotFoundError(ManagedAgentError):
    """Skill not found in registry."""


class SkillInvocationError(ManagedAgentError):
    """Skill execution failure."""


class MemoryStoreError(ManagedAgentError):
    """Memory persistence failure."""


class VaultError(ManagedAgentError):
    """Credential storage failure."""


class APIError(ManagedAgentError):
    """API call failure."""


class APIRateLimitError(APIError):
    """Rate limit exceeded."""


class EnvironmentError(ManagedAgentError):
    """Sandbox environment failure."""


class BridgeError(ManagedAgentError):
    """cc-connect bridge communication failure."""


class ConfigError(ManagedAgentError):
    """Configuration error."""
