"""项目统一的测试入口。

约定：app/ 下的模块互相之间、以及测试文件，都使用顶层导入
（例如 ``from tool_core import ToolResult``）。
本脚本把 app/ 加入模块搜索路径，因此不需要再手动设置 PYTHONPATH。

用法：
    python run_tests.py
    python run_tests.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
APP_DIR = PROJECT_ROOT / "app"
TEST_DIR = PROJECT_ROOT / "test"


def build_argv() -> list[str]:
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    argv = ["unittest", "discover", "-s", str(TEST_DIR), "-p", "test_*.py"]
    if verbose:
        argv.append("-v")
    return argv


def main() -> int:
    for directory in (APP_DIR, TEST_DIR):
        if not directory.is_dir():
            print(f"缺少目录：{directory}")
            return 1

    # 只把 app/ 加入搜索路径：如果某个文件写成 from app.xxx import，
    # 它会立刻报 ModuleNotFoundError，而不是悄悄变成另一份模块对象。
    sys.path.insert(0, str(APP_DIR))

    program = unittest.main(module=None, argv=build_argv(), exit=False)
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
