#!/usr/bin/env python3
"""
Book.txt 完整测试脚本
使用完整书籍文件测试模型性能
"""

import requests
import time
import json
from datetime import datetime
from pathlib import Path

OLLAMA_URL = "http://localhost:11434"
BOOK_FILE = Path(__file__).parent.parent.parent.parent / "book.txt"
REPORT_DIR = Path(__file__).parent
LOG_FILE = REPORT_DIR / "logs" / "book_test_log.txt"

TEST_PROMPT = """分析以下小说文本，提取所有角色信息（姓名、年龄、外貌、性格、与主角关系等）。

小说内容：
{}

请以JSON格式输出角色列表。"""

class BookTestRunner:
    def __init__(self):
        self.results = []
        self.log_lines = []

    def log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {msg}"
        print(line)
        self.log_lines.append(line)

    def save_log(self):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(self.log_lines))

    def load_book(self, max_chars=8000):
        with open(BOOK_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        return content[:max_chars]

    def test_model(self, model_name, model_type="generation"):
        self.log(f"开始测试: {model_name} ({model_type})")

        book_content = self.load_book(8000)
        prompt = TEST_PROMPT.format(book_content)

        start_time = time.time()

        try:
            if model_type == "embedding":
                response = requests.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": model_name, "prompt": book_content},
                    timeout=300
                )
                elapsed = time.time() - start_time
                result = response.json()
                embed_dim = len(result.get("embedding", []))

                self.log(f"  ✅ 完成: 耗时 {elapsed:.2f}s, 向量维度 {embed_dim}")

                return {
                    "model": model_name,
                    "type": model_type,
                    "elapsed": elapsed,
                    "success": embed_dim > 0,
                    "detail": f"向量维度: {embed_dim}"
                }
            else:
                response = requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 2048}
                    },
                    timeout=300
                )

                elapsed = time.time() - start_time
                result = response.json()

                tokens = result.get("eval_count", 0)
                tps = tokens / elapsed if elapsed > 0 else 0
                output = result.get("response", "")

                success = "陆江仙" in output

                self.log(f"  ✅ 完成: 耗时 {elapsed:.2f}s, {tps:.1f} t/s")

                return {
                    "model": model_name,
                    "type": model_type,
                    "elapsed": elapsed,
                    "tokens": tokens,
                    "tps": tps,
                    "output_length": len(output),
                    "success": success,
                    "output_preview": output[:300]
                }

        except Exception as e:
            self.log(f"  ❌ 失败: {e}")
            return {"model": model_name, "type": model_type, "error": str(e)}

    def run(self):
        print("=" * 60)
        self.log("Book.txt 完整测试开始")
        print("=" * 60)

        book_content = self.load_book()
        self.log(f"书籍大小: {len(book_content):,} 字符")

        models = [
            ("embeddinggemma:latest", "embedding"),
            ("qwen2.5:0.5b", "generation"),
            ("qwen3:0.6b", "generation"),
        ]

        for model_name, model_type in models:
            result = self.test_model(model_name, model_type)
            self.results.append(result)
            time.sleep(1)

        self.save_log()
        self.save_data()
        self.generate_report()

    def save_data(self):
        data_file = REPORT_DIR / "data" / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data_file.parent.mkdir(parents=True, exist_ok=True)

        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)

        self.log(f"数据已保存: {data_file}")

    def generate_report(self):
        report_file = REPORT_DIR / "reports" / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        content = f"""# Book.txt 完整测试报告

## 测试信息
- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 测试文件: {BOOK_FILE.name}
- 测试内容: 前8000字符
- 测试模型数: {len(self.results)}

## 测试结果

| 模型 | 类型 | 耗时(秒) | 速度/维度 | Token数 | 输出长度 | 成功 |
|------|------|----------|----------|---------|----------|------|
"""

        for r in self.results:
            if "error" in r:
                content += f"| {r['model']} | {r['type']} | ERROR | - | - | - | ❌ |\n"
            elif r["type"] == "embedding":
                content += f"| {r['model']} | Embedding | {r['elapsed']:.2f} | {r['detail']} | - | - | {'✅' if r['success'] else '❌'} |\n"
            else:
                content += f"| {r['model']} | Generation | {r['elapsed']:.2f} | {r['tps']:.1f} t/s | {r['tokens']} | {r['output_length']} | {'✅' if r['success'] else '❌'} |\n"

        content += """
## 结论

"""
        gen_results = [r for r in self.results if r.get("type") == "generation" and "error" not in r]
        if gen_results:
            fastest = min(gen_results, key=lambda x: x["elapsed"])
            content += f"- **最快模型**: {fastest['model']} ({fastest['elapsed']:.2f}秒)\n"

            best_quality = max(gen_results, key=lambda x: len(x.get("output_preview", "")))
            content += f"- **最长输出**: {best_quality['model']} ({best_quality['output_length']}字符)\n"

        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"\n📄 报告已生成: {report_file}")

if __name__ == "__main__":
    runner = BookTestRunner()
    runner.run()
