#!/usr/bin/env python3
"""
情感语气演示 - 使用 espeak-ng 生成不同情感的语音对比
（开发环境演示版，生产环境请使用 CosyVoice2）

espeak-ng 使用韵律参数控制情感效果：
  - rate: 语速 (wpm, 默认175)
  - pitch: 音调 (0-99, 默认50)
  - amplitude: 音量 (0-200, 默认100)
"""

import os
import subprocess
import wave
import struct

OUTPUT_DIR = "demo_audio"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 角色：中年男性，对应 espeak 参数
VOICE = "zh"          # 中文普通话
BASE_RATE = 160       # 基础语速 wpm
BASE_PITCH = 38       # 基础音调（男声偏低）
BASE_AMP = 100        # 基础音量

# 情感场景定义
SCENES = [
    {
        "emotion":  "着急",
        "scene":    "前线战报突至，敌军逼近",
        "text":     "快去叫副将！敌军已过了渭水，现在就走！",
        # 高语速、略高音调
        "rate":     220,
        "pitch":    52,
        "amp":      115,
    },
    {
        "emotion":  "轻松",
        "scene":    "太平盛世，与旧友饮酒叙旧",
        "text":     "来来来，今日不谈公事，咱们就说说当年在军中的那些趣事。",
        # 慢语速、自然音调
        "rate":     140,
        "pitch":    42,
        "amp":      95,
    },
    {
        "emotion":  "低沉",
        "scene":    "朝堂宣判，处置叛将",
        "text":     "此人通敌叛国，罪证确凿。依律，诛九族。",
        # 最低语速、最低音调
        "rate":     120,
        "pitch":    25,
        "amp":      100,
    },
    {
        "emotion":  "激动",
        "scene":    "北击匈奴大胜，凯旋入城",
        "text":     "我们赢了！二十年了，匈奴终于退出了河南地！兄弟们，你们是大秦的英雄！",
        # 最高语速、最高音调、最大音量
        "rate":     240,
        "pitch":    62,
        "amp":      130,
    },
    {
        "emotion":  "愤怒",
        "scene":    "发现下属克扣军饷",
        "text":     "你还有脸来见我！那是将士们的血汗钱！你给我跪下！",
        # 快语速、低音调（压抑的怒火）、大音量
        "rate":     200,
        "pitch":    30,
        "amp":      140,
    },
    {
        "emotion":  "悲伤",
        "scene":    "挚友战场阵亡，亲自祭奠",
        "text":     "老东陵……你走得太早了。当年我们许下的誓言，还没来得及实现啊。",
        # 最慢语速、低音调、小音量
        "rate":     110,
        "pitch":    28,
        "amp":      80,
    },
    {
        "emotion":  "平静",
        "scene":    "例行公事，批阅文书",
        "text":     "诸位，这件事本官已经知道了，你们都先退下。",
        # 基础参数
        "rate":     BASE_RATE,
        "pitch":    BASE_PITCH,
        "amp":      BASE_AMP,
    },
    {
        "emotion":  "威严",
        "scene":    "始皇帝驾崩，主持哀悼仪式",
        "text":     "陛下驾崩，举国同悲。百官肃立，向陛下行最后的礼。",
        # 慢语速、很低音调、较大音量
        "rate":     130,
        "pitch":    20,
        "amp":      110,
    },
]


def synthesize(scene: dict, index: int) -> str:
    """调用 espeak-ng 合成单个场景的语音，返回文件路径。"""
    filename = f"{index:02d}_{scene['emotion']}.wav"
    filepath = os.path.join(OUTPUT_DIR, filename)

    cmd = [
        "espeak-ng",
        "-v", VOICE,
        "-s", str(scene["rate"]),    # 语速 (words per minute)
        "-p", str(scene["pitch"]),   # 音调 (0-99)
        "-a", str(scene["amp"]),     # 音量 (0-200)
        "-w", filepath,              # 输出 WAV 文件
        scene["text"],
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [错误] espeak-ng 失败: {result.stderr}")
        return ""

    size = os.path.getsize(filepath)
    # WAV: 44字节 header + 16bit PCM，估算时长
    duration = (size - 44) / 2 / 22050
    print(f"  文件: {filename}  ({duration:.1f}s)")
    return filepath


def get_wav_info(path: str) -> tuple[int, int, int]:
    """返回 (channels, sample_width, frame_rate)"""
    with wave.open(path, 'rb') as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate()


def concatenate_wavs(files: list[str], output: str, silence_ms: int = 800):
    """将多个 WAV 文件拼接，中间插入静默。"""
    if not files:
        return

    # 读取第一个文件获取参数
    ch, sw, rate = get_wav_info(files[0])
    silence_frames = int(rate * silence_ms / 1000)
    silence_data = b'\x00' * silence_frames * ch * sw

    with wave.open(output, 'wb') as out:
        out.setnchannels(ch)
        out.setsampwidth(sw)
        out.setframerate(rate)

        for i, f in enumerate(files):
            if not f or not os.path.exists(f):
                continue
            with wave.open(f, 'rb') as w:
                out.writeframes(w.readframes(w.getnframes()))
            # 在段落之间插入静默
            if i < len(files) - 1:
                out.writeframes(silence_data)


def main():
    print("=" * 65)
    print("  情感语气演示 - espeak-ng 韵律参数对比")
    print("  角色：中年男性（中文普通话）")
    print("=" * 65)
    print(f"\n输出目录: {os.path.abspath(OUTPUT_DIR)}\n")

    files = []
    for i, scene in enumerate(SCENES, 1):
        print(f"[{i}/{len(SCENES)}] {scene['emotion']}  ——  {scene['scene']}")
        print(f"  台词: {scene['text']}")
        print(f"  参数: 语速={scene['rate']}wpm  音调={scene['pitch']}  音量={scene['amp']}")
        path = synthesize(scene, i)
        files.append(path)
        print()

    # 合并为完整对比文件
    combined = os.path.join(OUTPUT_DIR, "00_全部情感对比.wav")
    valid_files = [f for f in files if f]
    concatenate_wavs(valid_files, combined)

    total_size = os.path.getsize(combined) / 1024
    print("=" * 65)
    print(f"合并文件: {combined}  ({total_size:.0f} KB)")
    print()
    print("各情感参数对比表:")
    print(f"  {'情感':<6} {'语速(wpm)':<10} {'音调':<8} {'音量'}")
    print(f"  {'─'*6} {'─'*10} {'─'*8} {'─'*8}")
    for s in SCENES:
        print(f"  {s['emotion']:<6} {s['rate']:<10} {s['pitch']:<8} {s['amp']}")
    print()
    print("注意：espeak-ng 是基于规则的语音引擎，音质较机械。")
    print("生产环境请使用 CosyVoice2 instruct2 模式获得自然语气。")
    print("=" * 65)


if __name__ == "__main__":
    main()
