"""
Policy-related exceptions.
"""


class PolicyDenied(Exception):
    """Raised when a policy check denies a request."""
    def __init__(self, message: str, code: int = -32003):
        self.message = message
        self.code = code
        super().__init__(message)