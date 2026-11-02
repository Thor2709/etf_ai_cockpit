"""Safe, actionable errors exposed by the optional MCP adapter."""

from __future__ import annotations


class MCPToolError(RuntimeError):
    """A business error that can be shown to the tool caller without a traceback."""

    def __init__(self, reason_code: str, message: str, next_step: str) -> None:
        self.reason_code = reason_code
        self.message = message
        self.next_step = next_step
        super().__init__(f"{reason_code}: {message}. {next_step}")


class MCPServerUnavailable(RuntimeError):
    """The optional MCP SDK is missing or does not provide the supported API."""


class ToolDiscoveryError(RuntimeError):
    """A tools module could not be loaded safely or declared a duplicate tool."""


class ConfirmationError(MCPToolError):
    def __init__(self, message: str = "A valid confirmation token is required") -> None:
        super().__init__("CONFIRMATION_REQUIRED", message, "Preview the change and retry with its confirm_token.")


class AuthorizationError(MCPToolError):
    def __init__(self, message: str = "This tool is not enabled for the current launch profile") -> None:
        super().__init__("TIER_NOT_ENABLED", message, "Restart the local server with the required tier enabled.")


class RateLimitError(MCPToolError):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "RATE_LIMIT_EXCEEDED",
            "The operation's rate limit has been reached",
            f"Wait at least {retry_after_seconds:.0f} seconds before retrying.",
        )


class InvalidCursorError(MCPToolError):
    def __init__(self) -> None:
        super().__init__("INVALID_CURSOR", "The paging cursor is invalid or expired", "Restart from the first page.")


class InvalidArgumentsError(MCPToolError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_ARGUMENTS", message, "Correct the arguments and retry.")
