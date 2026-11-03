class AppError(Exception):
    status_code = 400
    code = "invalid_operation"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Unauthenticated(AppError):
    status_code = 401
    code = "unauthenticated"


class InvalidOperation(AppError):
    status_code = 400
    code = "invalid_operation"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation"

    def __init__(self, fields: dict[str, str], message: str = "Validation failed") -> None:
        super().__init__(message)
        self.fields = fields
