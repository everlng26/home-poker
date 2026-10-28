class DomainError(Exception):
    """Ожидаемая ошибка бизнес-правила, безопасная для показа пользователю."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

