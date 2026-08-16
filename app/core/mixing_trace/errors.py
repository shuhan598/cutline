"""混料追溯计算阶段使用的领域异常。"""

class MixingTraceCalculationError(ValueError):
    """单台机台混料追溯计算中可隔离的业务错误。"""

    def __init__(self, reason: str, message: str):
        """内部辅助步骤【__init__】，为上层业务流程提供数据处理或共用判断。"""
        super().__init__(message)
        self.reason = reason
        self.message = message
