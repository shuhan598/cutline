import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _method_parameters(relative_path: str, class_name: str, method_name: str):
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method_node = next(
        node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    return tuple(argument.arg for argument in method_node.args.args)


def test_legacy_rate_strategy_module_is_deleted():
    assert not (PROJECT_ROOT / "app/core/net_rate/rate_strategy.py").exists()


def test_new_net_rate_chain_has_no_rate_strategy_injection():
    net_rate_source = (
        PROJECT_ROOT / "app/core/net_rate/net_rate_calculator.py"
    ).read_text(encoding="utf-8")

    assert "def __init__" not in net_rate_source
    assert _method_parameters(
        "app/service/cutline_pipeline.py",
        "CutlinePipeline",
        "__init__",
    ) == ("self",)
