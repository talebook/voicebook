#!/usr/bin/env python3
"""
TTS 对比 Demo: kokoro-onnx vs CosyVoice
测试中文语音合成效果
"""

import os
import sys

# 测试文本 - 模拟有声书场景
TEST_TEXT = """
在一个宁静的小镇上，住着一个名叫小明的男孩。他今年十岁，圆圆的脸蛋上总是挂着天真的笑容。

"爸爸，我长大后想成为一个伟大的科学家！"小明兴奋地说道。

父亲轻轻地摸了摸小明的头，说："好啊，孩子。只要你努力学习和探索，就一定能实现自己的梦想。"

小明握紧小拳头，眼中闪烁着坚定的光芒。从那天起，他开始认真读书，探索科学的奥秘。
"""

# 简化测试文本
SIMPLE_TEXT = "你好，欢迎收听智能有声书。这是一个测试语音合成效果的示例。"

def test_kokoro():
    """测试 kokoro-onnx"""
    print("=" * 60)
    print("测试 kokoro-onnx...")
    print("=" * 60)

    try:
        from kokoro_onnx import Kokoro

        # 检查模型文件
        model_path = "kokoro-v1.0.onnx"
        voices_path = "voices-v1.0.bin"

        if not os.path.exists(model_path):
            print(f"❌ 模型文件不存在: {model_path}")
            print("请下载模型文件:")
            print("  - https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx")
            print("  - https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin")
            return None

        print(f"✅ kokoro-onnx 已安装")

        # 加载模型
        kokoro = Kokoro(model_path, voices_path)

        # 查看可用音色
        voices = kokoro.list_voices()
        print(f"\n📋 可用音色数量: {len(voices)}")

        # 尝试找一个中文音色
        chinese_voice = None
        for voice in voices[:20]:  # 显示前20个
            print(f"  - {voice}")

        # 生成音频
        output_path = "output_kokoro.wav"
        print(f"\n🎤 正在生成音频...")
        samples, sample_rate = kokoro.create(SIMPLE_TEXT, voice="af_sarah", speed=1.0)

        # 保存
        import soundfile as sf
        sf.write(output_path, samples, sample_rate)
        print(f"✅ 音频已保存: {output_path}")

        return output_path

    except ImportError:
        print("❌ kokoro-onnx 未安装")
        print("安装命令: pip install kokoro-onnx soundfile")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        return None


def test_cosyvoice():
    """测试 CosyVoice"""
    print("\n" + "=" * 60)
    print("测试 CosyVoice...")
    print("=" * 60)

    try:
        from cosyvoice import CosyVoice

        print(f"✅ CosyVoice 已安装")

        # 加载模型
        cosyvoice = CosyVoice('cosyvoice-300m')

        # 生成音频
        output_path = "output_cosyvoice.wav"
        print(f"\n🎤 正在生成音频...")

        # CosyVoice 使用示例
        result = cosyvoice.inference(SIMPLE_TEXT, stream=False)
        result.to_wav_file(output_path)

        print(f"✅ 音频已保存: {output_path}")
        return output_path

    except ImportError:
        print("❌ CosyVoice 未安装")
        print("安装命令:")
        print("  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git")
        print("  cd CosyVoice && pip install -r requirements.txt")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        return None


def test_edge_tts():
    """测试 Edge TTS (作为参考)"""
    print("\n" + "=" * 60)
    print("测试 Edge TTS (参考对比)...")
    print("=" * 60)

    try:
        import edge_tts
        import asyncio

        async def generate():
            output_path = "output_edge.mp3"
            print(f"\n🎤 正在生成音频...")

            # 使用中文女声
            communicate = edge_tts.Communicate(SIMPLE_TEXT, "zh-CN-XiaoxiaoNeural")
            await communicate.save(output_path)

            print(f"✅ 音频已保存: {output_path}")
            return output_path

        return asyncio.run(generate())

    except ImportError:
        print("❌ Edge TTS 未安装")
        print("安装命令: pip install edge-tts")
        return None
    except Exception as e:
        print(f"❌ 错误: {e}")
        return None


def play_audio(file_path):
    """播放音频"""
    if file_path and os.path.exists(file_path):
        print(f"\n🔊 播放: {file_path}")
        os.system(f"open '{file_path}'" if sys.platform == "darwin" else f"xdg-open '{file_path}'")
    else:
        print(f"❌ 文件不存在: {file_path}")


def main():
    print("🎙️  TTS 对比测试")
    print("=" * 60)
    print()

    results = {}

    # 1. 测试 Edge TTS (最简单，先测试)
    edge_result = test_edge_tts()
    if edge_result:
        results["Edge TTS"] = edge_result

    # 2. 测试 kokoro-onnx
    kokoro_result = test_kokoro()
    if kokoro_result:
        results["kokoro-onnx"] = kokoro_result

    # 3. 测试 CosyVoice
    cosyvoice_result = test_cosyvoice()
    if cosyvoice_result:
        results["CosyVoice"] = cosyvoice_result

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    if results:
        print("\n成功生成的音频文件:")
        for name, path in results.items():
            print(f"  ✅ {name}: {path}")

        print("\n按任意键依次播放，或按 Ctrl+C 退出...")
        input()

        # 依次播放
        for name, path in results.items():
            print(f"\n{'='*40}")
            print(f"正在播放: {name}")
            print(f"{'='*40}")
            play_audio(path)
            if sys.platform == "darwin":
                input("按回车继续播放下一个...")
    else:
        print("\n❌ 没有成功生成任何音频文件")
        print("\n请先安装 TTS 库:")
        print("  pip install edge-tts")
        print("  pip install kokoro-onnx soundfile")
        print("  # CosyVoice 需要从源码安装")


if __name__ == "__main__":
    main()
