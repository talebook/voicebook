#!/usr/bin/env python3
"""
LLM 角色分析速度对比测试
测试不同模型在角色分析任务上的性能
"""

import time
import requests
import json
import psutil
import os

# 测试用的角色分析 Prompt
TEST_PROMPT = """分析以下小说片段中的角色：

"张伟是一名三十岁的程序员，他有着深邃的眼神和平静的性格。他从小就展现出对科技的浓厚兴趣。"

请用JSON格式输出：
{
  "characters": [
    {
      "name": "角色名",
      "age": 年龄,
      "gender": "男/女",
      "personality": "性格特点",
      "appearance": "外貌特征"
    }
  ]
}
"""

def test_model(model_name: str, prompt: str) -> dict:
    """测试单个模型的性能"""
    start_time = time.time()
    start_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB

    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 512
                }
            },
            timeout=120
        )

        end_time = time.time()
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB

        result = response.json()
        elapsed = end_time - start_time
        memory_used = end_memory - start_memory

        return {
            "success": True,
            "model": model_name,
            "elapsed_time": elapsed,
            "memory_used": memory_used,
            "tokens": result.get("eval_count", 0),
            "tokens_per_second": result.get("eval_count", 0) / elapsed if elapsed > 0 else 0,
            "response": result.get("response", "")[:200]
        }

    except Exception as e:
        return {
            "success": False,
            "model": model_name,
            "error": str(e)
        }

def get_ollama_models():
    """获取已安装的 Ollama 模型"""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = response.json().get("models", [])
        return [m["name"] for m in models]
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []

def main():
    print("=" * 70)
    print("LLM 角色分析性能对比测试")
    print("=" * 70)

    # 检查 Ollama 服务
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        print("✅ Ollama 服务正常运行\n")
    except Exception as e:
        print(f"❌ Ollama 服务未运行: {e}")
        print("请先启动 Ollama: ollama serve")
        return

    # 获取可用模型
    models = get_ollama_models()

    if not models:
        print("❌ 没有找到已安装的模型")
        print("\n请先安装模型:")
        print("  ollama pull qwen3:0.6b")
        print("  ollama pull qwen2.5:0.5b")
        print("  ollama pull llama3.2:1b")
        return

    print(f"📋 发现 {len(models)} 个已安装模型:")
    for m in models:
        print(f"  - {m}")
    print()

    # 测试每个模型
    results = []
    for model in models:
        print(f"⏳ 测试 {model}...")
        result = test_model(model, TEST_PROMPT)
        results.append(result)

        if result["success"]:
            print(f"  ✅ 完成!")
            print(f"     耗时: {result['elapsed_time']:.2f}秒")
            print(f"     速度: {result['tokens_per_second']:.1f} tokens/秒")
        else:
            print(f"  ❌ 失败: {result.get('error', 'Unknown error')}")
        print()

    # 输出汇总
    print("=" * 70)
    print("📊 测试结果汇总")
    print("=" * 70)

    success_results = [r for r in results if r["success"]]

    if success_results:
        # 按速度排序
        success_results.sort(key=lambda x: x["tokens_per_second"], reverse=True)

        print(f"\n{'模型':<25} {'耗时(秒)':<12} {'速度(t/s)':<12} {'排名'}")
        print("-" * 60)

        for i, r in enumerate(success_results, 1):
            print(f"{r['model']:<25} {r['elapsed_time']:<12.2f} {r['tokens_per_second']:<12.1f} #{i}")

        print("\n🏆 最快模型:", success_results[0]["model"])
        print("   速度:", f"{success_results[0]['tokens_per_second']:.1f} tokens/秒")

    # 保存结果
    with open("llm_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n📁 结果已保存到: llm_benchmark_results.json")

if __name__ == "__main__":
    main()
