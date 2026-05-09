#!/usr/bin/env python3
"""
TTS 对比测试 - 简化版
使用 Edge TTS 和 kokoro-onnx 进行对比
CosyVoice 需要 Docker 环境才能运行
"""

import os
import sys
import asyncio

# 测试文本
TEST_TEXT = "你好，欢迎收听智能有声书。这是一个测试语音合成效果的示例。"

def test_kokoro():
    """测试 kokoro-onnx"""
    print("=" * 60)
    print("测试 kokoro-onnx...")
    print("=" * 60)

    try:
        from kokoro_onnx import Kokoro

        model_path = "models/kokoro-v1.0.onnx"
        voices_path = "models/voices-v1.0.bin"

        if not os.path.exists(model_path):
            print(f"❌ 模型文件不存在")
            return None

        print(f"✅ kokoro-onnx 已安装")
        print(f"📥 加载模型...")

        kokoro = Kokoro(model_path, voices_path)
        voices = kokoro.get_voices()

        print(f"\n📋 可用音色数量: {len(voices)}")

        # 找一个中文音色
        chinese_voice = None
        for voice in voices:
            if 'zh' in voice.lower():
                chinese_voice = voice
                break

        if not chinese_voice:
            chinese_voice = voices[0]

        print(f"\n🎤 使用音色: {chinese_voice}")

        output_path = "output_kokoro.wav"
        samples, sample_rate = kokoro.create(TEST_TEXT, voice=chinese_voice, speed=1.0)

        import soundfile as sf
        sf.write(output_path, samples, sample_rate)
        print(f"✅ 音频已保存: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_edge_tts():
    """测试 Edge TTS"""
    print("\n" + "=" * 60)
    print("测试 Edge TTS (微软中文)...")
    print("=" * 60)

    try:
        import edge_tts

        async def generate():
            output_path = "output_edge.mp3"
            print(f"🎤 正在生成音频...")

            communicate = edge_tts.Communicate(TEST_TEXT, "zh-CN-XiaoxiaoNeural")
            await communicate.save(output_path)

            print(f"✅ 音频已保存: {output_path}")
            return output_path

        return asyncio.run(generate())

    except Exception as e:
        print(f"❌ 错误: {e}")
        return None


def main():
    print("🎙️  TTS 对比测试")
    print("=" * 60)
    print(f"\n测试文本: {TEST_TEXT}")
    print()
    print("说明: CosyVoice 需要 Docker 环境才能运行")
    print("=" * 60)

    results = {}

    # 1. Edge TTS
    edge_result = test_edge_tts()
    if edge_result:
        results["Edge TTS (微软中文)"] = edge_result

    # 2. kokoro-onnx
    kokoro_result = test_kokoro()
    if kokoro_result:
        results["kokoro-onnx"] = kokoro_result

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果")
    print("=" * 60)

    if results:
        for name, path in results.items():
            size = os.path.getsize(path) / 1024
            print(f"  ✅ {name}: {path} ({size:.1f}KB)")

        print("\n" + "=" * 60)
        print("播放命令:")
        print("=" * 60)
        for name, path in results.items():
            print(f"\n  【{name}】")
            print(f"  open {path}")

        # 自动播放第一个
        first = list(results.values())[0]
        print(f"\n▶️  正在播放: {first}")
        os.system(f"open '{first}'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
