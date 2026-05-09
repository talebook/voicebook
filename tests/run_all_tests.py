#!/usr/bin/env python3
"""
Book2Audio 测试套件 - 统一运行器
"""

import sys
import subprocess
from pathlib import Path
from datetime import datetime

TESTS_DIR = Path(__file__).parent

def run_test(test_name, script):
    print(f"\n{'='*60}")
    print(f"运行测试: {test_name}")
    print("=" * 60)

    script_path = TESTS_DIR / script
    if not script_path.exists():
        print(f"❌ 脚本不存在: {script_path}")
        return False

    try:
        result = subprocess.run(
            ["python3", str(script_path)],
            capture_output=False,
            text=True,
            cwd=TESTS_DIR
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        return False

def main():
    print("=" * 60)
    print("Book2Audio 测试套件")
    print("=" * 60)

    tests = [
        ("LLM Benchmark", "llm_benchmark_20260509/scripts/benchmark.py"),
        ("Book Test", "book_test_20260509/scripts/book_test.py"),
    ]

    results = {}
    for name, script in tests:
        success = run_test(name, script)
        results[name] = "✅" if success else "❌"

    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)
    for name, status in results.items():
        print(f"  {status} {name}")

    print(f"\n测试报告目录: {TESTS_DIR}")
    print("  - logs/: 执行日志")
    print("  - data/: 测试数据(JSON)")
    print("  - reports/: 测试报告(Markdown)")

if __name__ == "__main__":
    main()
