class MixingTraceCalculationError(ValueError):
    """单台机台混料追溯计算中可隔离的业务错误。"""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message
