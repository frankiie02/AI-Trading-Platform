import ast
import importlib
from pathlib import Path

LEGACY_TOP_LEVEL_MODULES = (
    "data",
    "strategies",
    "engine",
    "risk",
    "models",
    "analytics",
)


def test_main_module_imports_no_archived_legacy_modules():
    main_source_path = Path(__file__).resolve().parents[2] / "main.py"
    tree = ast.parse(main_source_path.read_text())

    imported_modules = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    for module_name in imported_modules:
        top_level = module_name.split(".")[0]
        assert top_level not in LEGACY_TOP_LEVEL_MODULES, (
            f"main.py must not import legacy module '{module_name}'"
        )


def test_main_runs_cleanly_in_default_research_mode(monkeypatch, capsys):
    main_module = importlib.import_module("main")

    monkeypatch.setattr(
        "core.runtime.application.TradingApplication._load_settings",
        lambda self: {"RUNTIME_MODE": "research"},
    )

    exit_code = main_module.main()

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "research" in captured.out


def test_main_reports_controlled_error_for_invalid_mode(monkeypatch, capsys):
    main_module = importlib.import_module("main")

    monkeypatch.setattr(
        "core.runtime.application.TradingApplication._load_settings",
        lambda self: {"RUNTIME_MODE": "not_a_real_mode"},
    )

    exit_code = main_module.main()

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Runtime configuration error" in captured.out
