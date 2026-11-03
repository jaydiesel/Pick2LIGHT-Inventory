class AppError(Exception):
    """Base for errors that map to the API's standard error body."""

    code = "invalid_operation"
    status_code = 400

    def __init__(self, message: str, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fields = fields


class NotFound(AppError):
    code = "not_found"
    status_code = 404


class Conflict(AppError):
    code = "conflict"
    status_code = 409


class InvalidOperation(AppError):
    code = "invalid_operation"
    status_code = 400


class ValidationFailed(AppError):
    code = "validation"
    status_code = 422

    def __init__(self, fields: dict[str, str], message: str = "Validation failed") -> None:
        super().__init__(message, fields)
