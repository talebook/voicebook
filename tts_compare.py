#!/usr/bin/env python3
"""
TTS 对比测试 - CosyVoice vs kokoro-onnx
"""

import os
import sys
sys.path.insert(0, '/tmp/CosyVoice')

# 测试文本
TEST_TEXT = "你好，欢迎收听智能有声书。这是一个测试语音合成效果的示例。"

def test_cosyvoice():
    """测试 CosyVoice"""
    print("=" * 60)
    print("测试 CosyVoice...")
    print("=" * 60)

    try:
        from cosyvoice.cli.cosyvoice import CosyVoice
        import torchaudio

        print(f"✅ CosyVoice 已安装")

        # 加载模型
        print(f"📥 加载模型...")
        model_dir = 'pretrained_models/CosyVoice-300M-SFT'
        cosyvoice = CosyVoice(model_dir)

        # 查看可用音色
        print(f"\n📋 可用音色:")
        for spk in cosyvoice.list_available_spks():
            print(f"  - {spk}")

        # 生成音频
        output_path = "output_cosyvoice.wav"
        print(f"\n🎤 正在生成音频...")

        # 使用中文女声
        result = cosyvoice.inference_sft(TEST_TEXT, '中文女', stream=False)
        torchaudio.save(output_path, result['tts_speech'], cosyvoice.sample_rate)

        print(f"✅ 音频已保存: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_kokoro():
    """测试 kokoro-onnx"""
    print("\n" + "=" * 60)
    print("测试 kokoro-onnx...")
    print("=" * 60)

    try:
        from kokoro_onnx import Kokoro

        # 模型路径
        model_path = "models/kokoro-v1.0.onnx"
        voices_path = "models/voices-v1.0.bin"

        if not os.path.exists(model_path):
            print(f"❌ 模型文件不存在: {model_path}")
            return None

        print(f"✅ kokoro-onnx 已安装")

        # 加载模型
        print(f"📥 加载模型...")
        kokoro = Kokoro(model_path, voices_path)

        # 获取可用音色
        voices = kokoro.get_voices()
        print(f"\n📋 可用音色数量: {len(voices)}")

        # 找一个中文音色
        chinese_voice = None
        for voice in voices:
            voice_str = str(voice).lower()
            if 'zh' in voice_str or 'cantonese' in voice_str or 'mandarin' in voice_str or 'chinese' in voice_str:
                chinese_voice = voice
                print(f"\n  🎯 找到中文音色: {chinese_voice}")
                break

        # 如果没找到，尝试用第一个
        if not chinese_voice and voices:
            chinese_voice = voices[0]
            print(f"\n  🎯 使用默认音色: {chinese_voice}")

        if not chinese_voice:
            print("❌ 没有找到可用音色")
            return None

        # 生成音频
        output_path = "output_kokoro.wav"
        print(f"\n🎤 正在生成音频 (音色: {chinese_voice})...")

        samples, sample_rate = kokoro.create(TEST_TEXT, voice=chinese_voice, speed=1.0)

        # 保存
        import soundfile as sf
        sf.write(output_path, samples, sample_rate)
        print(f"✅ 音频已保存: {output_path}")
        return output_path

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("🎙️  TTS 对比测试: CosyVoice vs kokoro-onnx")
    print("=" * 60)
    print(f"\n测试文本: {TEST_TEXT}")
    print()

    results = {}

    # 1. 测试 CosyVoice
    cosyvoice_result = test_cosyvoice()
    if cosyvoice_result:
        results["1. CosyVoice"] = cosyvoice_result

    # 2. 测试 kokoro-onnx
    kokoro_result = test_kokoro()
    if kokoro_result:
        results["2. kokoro-onnx"] = kokoro_result

    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    if results:
        print("\n成功生成的音频文件:")
        for name, path in results.items():
            file_size = os.path.getsize(path) / 1024
            print(f"  ✅ {name}: {path} ({file_size:.1f}KB)")

        print("\n" + "=" * 60)
        print("音频文件已生成！")
        print("=" * 60)
        print("\n请手动使用以下命令播放对比:")
        print("  open output_cosyvoice.wav")
        print("  open output_kokoro.wav")

    else:
        print("\n❌ 没有成功生成任何音频文件")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
