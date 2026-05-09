#!/usr/bin/env python3
"""
LLM Benchmark 测试脚本
测试不同 Ollama 模型在中文角色分析任务上的性能
"""

import requests
import time
import json
import sys
from datetime import datetime
from pathlib import Path

# 配置
OLLAMA_URL = "http://localhost:11434"
TEST_PROMPT = """分析以下小说文本，提取所有角色信息（姓名、年龄、外貌、性格、与主角关系等）。

小说内容：
陆江仙做了一个很长很长的梦，梦见田间种稻，梦见刀光剑影，梦见仙宗、女子、大湖。

"将《太阴吐纳练气诀》与《月华纪要秘旨》交出，我等可以只废去你修为。"

一道悦耳又冰冷的女声在耳边响起，陆江仙隐隐约约看见一张朦胧的脸庞，却什么也看不清楚。

"咣当！"

剧烈的摇晃感一下子将陆江仙惊醒。

光怪陆离的色彩在脑海中浮现，陆江仙想睁开眼，想起身，身体如同鬼压床般对他的指挥毫不理睬。

这时，一道灿烂的白光划破眼前的浓密的黑暗，虽然黑暗如同潮水一般不断涌来，但那道光柱始终矗立着，太阳一般亘古不变。

密密麻麻的金色咒文从中迸发而出，在黑暗中舒展着身体，像星辰一样撒满天空。

"好美。"陆江仙呆呆地想着

随着咒文越来越多，彷佛到达了某个极限，他听到了如同玻璃破碎的卡察声

世界，亮了。

陆江仙看见了蔚然如大海的天空，茂密的无边无际的原始森林，不远处是弯月型的小湖，在那个方向，一道白色的流光滑落在波光粼粼的小湖中。

下方坐落着一小片秸秆扎成顶的小屋和成片的稻田。

剧烈翻滚的视角中，他像一只轻飘飘的燕雀飞过褐黄色的小小的村落和烟火，从清澈的小河上空划过。

惊鸿一瞥中，陆江仙望见了小河中自己的倒影。

"好像是一个圆形的，闪闪发光的东西......"陆江仙迷茫地想着，一种隐约的预兆浮现在心头：

"我不做人了？"

"哗啦！"剧烈的摇晃再次袭来，陆江仙迅速沉入水中，小河太浅不足以化解所有冲击力，于是他轻轻地磕在了小河底的青石之上。

这么一磕让陆江仙感觉像是被人在胸前干了一拳，有些胸闷气短，倒是自己的身体借助激荡的河水和撞击的反冲力稳稳的翻了个身，成了正面朝上，正对着河面上水波荡漾的太阳。

"我不是在出租房中熬夜改方桉么？"

请以JSON格式输出角色列表。"""

REPORT_DIR = Path(__file__).parent
LOG_FILE = REPORT_DIR / "logs" / "benchmark_log.txt"

class BenchmarkRunner:
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
        self.log(f"日志已保存: {LOG_FILE}")

    def check_ollama(self):
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            return r.status_code == 200
        except:
            return False

    def get_models(self):
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]

    def test_model(self, model_name):
        self.log(f"开始测试模型: {model_name}")
        start_time = time.time()

        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": model_name,
                    "prompt": TEST_PROMPT,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 512
                    }
                },
                timeout=120
            )

            elapsed = time.time() - start_time
            result = response.json()

            tokens = result.get("eval_count", 0)
            tps = tokens / elapsed if elapsed > 0 else 0
            output = result.get("response", "")

            success = "陆江仙" in output

            self.log(f"  ✅ 完成: 耗时 {elapsed:.2f}s, 速度 {tps:.1f} t/s")

            return {
                "model": model_name,
                "elapsed": elapsed,
                "tokens": tokens,
                "tps": tps,
                "output_length": len(output),
                "success": success,
                "output_preview": output[:200]
            }

        except Exception as e:
            self.log(f"  ❌ 失败: {e}")
            return {
                "model": model_name,
                "error": str(e)
            }

    def run(self):
        print("=" * 60)
        self.log("LLM Benchmark 测试开始")
        print("=" * 60)

        if not self.check_ollama():
            print("❌ Ollama 服务未运行")
            self.log("错误: Ollama 服务未运行")
            return

        self.log("Ollama 服务正常")

        models = self.get_models()
        self.log(f"发现 {len(models)} 个模型: {', '.join(models)}")

        print(f"\n测试模型列表: {models}\n")

        for model in models:
            result = self.test_model(model)
            self.results.append(result)
            time.sleep(1)

        self.save_log()
        self.generate_report()

    def generate_report(self):
        report_file = REPORT_DIR / "reports" / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        content = f"""# LLM Benchmark 测试报告

## 测试信息
- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- 测试任务: 中文小说角色分析
- 测试模型数: {len(self.results)}

## 测试结果

| 模型 | 耗时(秒) | 速度(t/s) | Token数 | 输出长度 | 成功 |
|------|----------|----------|---------|----------|------|
"""

        for r in self.results:
            if "error" in r:
                content += f"| {r['model']} | ERROR | - | - | - |\n"
            else:
                success = "✅" if r.get("success") else "❌"
                content += f"| {r['model']} | {r['elapsed']:.2f} | {r['tps']:.1f} | {r['tokens']} | {r['output_length']} | {success} |\n"

        content += """
## 详细输出

"""
        for r in self.results:
            if "error" not in r:
                content += f"### {r['model']}\n\n```\n{r['output_preview']}\n```\n\n"

        content += """
## 结论

"""
        best = min([r for r in self.results if "error" not in r], key=lambda x: x["elapsed"], default=None)
        if best:
            content += f"- 最快模型: {best['model']} ({best['elapsed']:.2f}秒)\n"
            content += f"- 最高吞吐: {max(self.results, key=lambda x: x.get('tps', 0))['model']}\n"

        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"\n📄 报告已生成: {report_file}")

if __name__ == "__main__":
    runner = BenchmarkRunner()
    runner.run()
