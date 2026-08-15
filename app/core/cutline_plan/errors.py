"""机台选择及虚拟影响评估阶段使用的领域异常。"""

class MachineSelectionEvaluationError(ValueError):
    """逐台选择或影响模拟无法执行时抛出的异常。"""
