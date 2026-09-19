class WorkflowError(ValueError):
    """A stable, content-free failure for HTTP and MCP adapters."""

    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
