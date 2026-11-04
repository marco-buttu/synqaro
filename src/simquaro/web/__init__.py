"""Local GUI services; optional HTTP packages are imported only by app.py."""


class ServiceError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)
