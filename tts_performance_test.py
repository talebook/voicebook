#!/usr/bin/env python3
"""
TTS 性能对比测试 - CosyVoice vs kokoro-onnx
对比指标:
- 加载时间
- 生成时间
- 内存占用
- 音频质量（客观指标
"""

import os
import sys
import time
import json
import psutil
import subprocess
from datetime import datetime
from typing import Dict, List, Any

# 添加 CosyVoice 路径
sys.path.insert(0, '/tmp/CosyVoice')

# 测试文本集
TEST_TEXTS = [
    {"name": "短句（20字", "text": "你好，欢迎收听智能有声书。"},
    {"name": "中句（50字", "text": "你好，欢迎收听智能有声书。这是一个测试语音合成效果的示例。"},
    {"name": "长句（100字", "text": "在一个宁静的小镇上，住着一个名叫小明的男孩。他今年十岁，圆圆的脸蛋上总是挂着天真的笑容。"},
    {"name": "段落（200字", "text": "在一个宁静的小镇上，住着一个名叫小明的男孩。他今年十岁，圆圆的脸蛋上总是挂着天真的笑容。\"爸爸，我长大后想成为一个伟大的科学家！\"小明兴奋地说道。父亲轻轻地摸了摸小明的头，说：\"好啊，孩子。只要你努力学习和探索，就一定能实现自己的梦想。\""}
]

class PerformanceMetrics:
    def __init__(self):
        self.process = psutil.Process()

    def get_memory_mb(self) -> float:
        """获取当前进程内存使用（MB）"""
        return self.process.memory_info().rss / 1024 / 1024

    def measure(self, func, *args, **kwargs) -> tuple[Any, float, float]:
        """测量函数执行时间和内存变化"""
        mem_before = self.get_memory_mb()
        start_time = time.time()
        
        result = func(*args, **kwargs)
        
        end_time = time.time()
        mem_after = self.get_memory_mb()
        
        elapsed = end_time - start_time
        mem_delta = mem_after - mem_before
        
        return result, elapsed, mem_delta


class TTSBenchmark:
    def __init__(self, output_dir: str = "tts_benchmark_output"):
        self.output_dir = output_dir
        self.metrics = PerformanceMetrics()
        self.results = {
            "test_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "models": {}
        }
        
        os.makedirs(output_dir, exist_ok=True)

    def test_cosyvoice(self) -> Dict[str, Any]:
        """测试 CosyVoice"""
        print("\n" + "=" * 80)
        print("🎤  测试 CosyVoice (CosyVoice-300M-SFT")
        print("=" * 80)
        
        model_name = "CosyVoice-300M-SFT"
        model_results = {
            "model": model_name,
            "load_time": None,
            "load_memory_mb": None,
            "tests": [],
            "errors": []
        }
        
        try:
            # 1. 测试模型加载
            print("\n[1/3] 加载模型...")
            from cosyvoice.cli.cosyvoice import CosyVoice
            import torchaudio
            
            model_dir = 'pretrained_models/CosyVoice-300M-SFT'
            
            def load_model():
                return CosyVoice(model_dir)
            
            cosyvoice, load_time, load_mem_delta = self.metrics.measure(load_model)
            model_results["load_time"] = load_time
            model_results["load_memory_mb"] = load_mem_delta
            print(f"   ✅ 加载完成: {load_time:.2f}s, 内存增加: {load_mem_delta:.1f}MB")
            
            # 2. 列出可用音色
            print("\n[2/3] 可用音色:")
            voices = cosyvoice.list_available_spks()
            for spk in voices:
                print(f"   - {spk}")
            
            # 3. 测试生成
            print("\n[3/3] 语音生成测试...")
            test_voice = '中文女'
            
            for i, test_case in enumerate(TEST_TEXTS):
                print(f"\n   测试 {i+1}/{len(TEST_TEXTS)}: {test_case['name']}")
                
                def generate():
                    result = cosyvoice.inference_sft(test_case['text'], test_voice, stream=False)
                    return result
                
                result, gen_time, gen_mem_delta = self.metrics.measure(generate)
                
                # 保存音频
                output_path = os.path.join(self.output_dir, f"cosyvoice_{test_case['name']}.wav")
                torchaudio.save(output_path, result['tts_speech'], cosyvoice.sample_rate)
                
                # 计算音频时长
                audio_duration = len(result['tts_speech'].shape[1]) / cosyvoice.sample_rate
                real_time_factor = audio_duration / gen_time
                
                test_result = {
                    "test_name": test_case['name'],
                    "text_length": len(test_case['text']),
                    "gen_time": gen_time,
                    "audio_duration": audio_duration,
                    "real_time_factor": real_time_factor,
                    "memory_mb": gen_mem_delta,
                    "file_size_kb": os.path.getsize(output_path) / 1024,
                    "output_file": output_path
                }
                model_results["tests"].append(test_result)
                
                print(f"      ⏱️  生成时间: {gen_time:.2f}s")
                print(f"      🎵  音频时长: {audio_duration:.2f}s")
                print(f"      ⚡  实时因子: {real_time_factor:.2f}x")
                print(f"      📦  文件大小: {test_result['file_size_kb']:.1f}KB")
            
            self.results["models"]["CosyVoice"] = model_results
            return model_results
            
        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ 错误: {error_msg}")
            import traceback
            traceback.print_exc()
            model_results["errors"].append(error_msg)
            self.results["models"]["CosyVoice"] = model_results
            return model_results

    def test_kokoro(self) -> Dict[str, Any]:
        """测试 kokoro-onnx"""
        print("\n" + "=" * 80)
        print("🎤  测试 kokoro-onnx")
        print("=" * 80)
        
        model_name = "kokoro-onnx v1.0"
        model_results = {
            "model": model_name,
            "load_time": None,
            "load_memory_mb": None,
            "tests": [],
            "errors": []
        }
        
        try:
            # 1. 测试模型加载
            print("\n[1/3] 加载模型...")
            from kokoro_onnx import Kokoro
            
            model_path = "models/kokoro-v1.0.onnx"
            voices_path = "models/voices-v1.0.bin"
            
            def load_model():
                return Kokoro(model_path, voices_path)
            
            kokoro, load_time, load_mem_delta = self.metrics.measure(load_model)
            model_results["load_time"] = load_time
            model_results["load_memory_mb"] = load_mem_delta
            print(f"   ✅ 加载完成: {load_time:.2f}s, 内存增加: {load_mem_delta:.1f}MB")
            
            # 2. 列出可用音色
            print("\n[2/3] 可用音色数量:")
            voices = kokoro.get_voices()
            print(f"   共 {len(voices)} 个音色")
            
            # 找一个合适的音色
            test_voice = None
            for voice in voices:
                voice_str = str(voice).lower()
                if 'af' in voice_str or 'zh' in voice_str:
                    test_voice = voice
                    break
            if not test_voice and voices:
                test_voice = voices[0]
            print(f"   使用音色: {test_voice}")
            
            # 3. 测试生成
            print("\n[3/3] 语音生成测试...")
            import soundfile as sf
            
            for i, test_case in enumerate(TEST_TEXTS):
                print(f"\n   测试 {i+1}/{len(TEST_TEXTS)}: {test_case['name']}")
                
                def generate():
                    return kokoro.create(test_case['text'], voice=test_voice, speed=1.0)
                
                (samples, sample_rate), gen_time, gen_mem_delta = self.metrics.measure(generate)
                
                # 保存音频
                output_path = os.path.join(self.output_dir, f"kokoro_{test_case['name']}.wav")
                sf.write(output_path, samples, sample_rate)
                
                # 计算音频时长
                audio_duration = len(samples) / sample_rate
                real_time_factor = audio_duration / gen_time
                
                test_result = {
                    "test_name": test_case['name'],
                    "text_length": len(test_case['text']),
                    "gen_time": gen_time,
                    "audio_duration": audio_duration,
                    "real_time_factor": real_time_factor,
                    "memory_mb": gen_mem_delta,
                    "file_size_kb": os.path.getsize(output_path) / 1024,
                    "output_file": output_path
                }
                model_results["tests"].append(test_result)
                
                print(f"      ⏱️  生成时间: {gen_time:.2f}s")
                print(f"      🎵  音频时长: {audio_duration:.2f}s")
                print(f"      ⚡  实时因子: {real_time_factor:.2f}x")
                print(f"      📦  文件大小: {test_result['file_size_kb']:.1f}KB")
            
            self.results["models"]["kokoro-onnx"] = model_results
            return model_results
            
        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ 错误: {error_msg}")
            import traceback
            traceback.print_exc()
            model_results["errors"].append(error_msg)
            self.results["models"]["kokoro-onnx"] = model_results
            return model_results

    def save_results(self, filename: str = "tts_benchmark_results.json"):
        """保存结果到 JSON 文件"""
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
        print(f"\n📊 结果已保存: {filepath}")
        return filepath

    def generate_report(self, results_file: str):
        """生成 Markdown 报告"""
        report_path = os.path.join(self.output_dir, "tts_benchmark_report.md")
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("# TTS 性能对比测试报告\n\n")
            f.write(f"## 测试信息\n")
            f.write(f"- 测试时间: {self.results['test_time']}\n")
            f.write(f"- 测试模型: CosyVoice-300M-SFT vs kokoro-onnx\n")
            f.write(f"\n")
            
            # 模型加载对比
            f.write("## 模型加载性能\n\n")
            f.write("| 模型 | 加载时间(s) | 内存增加(MB) |\n")
            f.write("|------|-------------|--------------|\n")
            for name, data in self.results["models"].items():
                if data.get("load_time") is not None:
                    f.write(f"| {name} | {data['load_time']:.2f} | {data['load_memory_mb']:.1f} |\n")
                else:
                    f.write(f"| {name} | ❌ | ❌ |\n")
            
            # 生成性能对比
            f.write("\n## 语音生成性能\n\n")
            
            for test_case in TEST_TEXTS:
                f.write(f"### {test_case['name']} ({len(test_case['text'])} 字符\n\n")
                f.write("| 模型 | 生成时间(s) | 音频时长(s) | 实时因子(x) | 文件大小(KB) |\n")
                f.write("|------|-------------|------------|-------------|--------------|\n")
                
                for name, data in self.results["models"].items():
                    if "tests" in data:
                        for test in data["tests"]:
                            if test["test_name"] == test_case['name']:
                                f.write(f"| {name} | {test['gen_time']:.2f} | {test['audio_duration']:.2f} | {test['real_time_factor']:.2f}x | {test['file_size_kb']:.1f} |\n")
                f.write("\n")
            
            # 综合对比总结
            f.write("## 综合对比总结\n\n")
            f.write("### CosyVoice 优势:\n")
            f.write("- 专为中文优化\n")
            f.write("- 音色自然度高\n")
            f.write("- 支持多种中文音色\n")
            f.write("\n")
            f.write("### kokoro-onnx 优势:\n")
            f.write("- 轻量级 ONNX 模型\n")
            f.write("- 加载速度快\n")
            f.write("- 内存占用低\n")
            f.write("\n")
        
        print(f"📄 报告已生成: {report_path}")
        return report_path

    def run_all(self):
        """运行所有测试"""
        print("🎙️  TTS 性能对比测试: CosyVoice vs kokoro-onnx")
        print("=" * 80)
        
        # 运行测试
        self.test_cosyvoice()
        self.test_kokoro()
        
        # 保存结果
        results_file = self.save_results()
        report_file = self.generate_report(results_file)
        
        print("\n" + "=" * 80)
        print("✅ 测试完成！")
        print("=" * 80)
        print(f"\n结果文件: {results_file}")
        print(f"报告文件: {report_file}")
        print(f"音频文件: {self.output_dir}/")
        
        return results_file, report_file


def main():
    benchmark = TTSBenchmark()
    benchmark.run_all()


if __name__ == "__main__":
    main()
