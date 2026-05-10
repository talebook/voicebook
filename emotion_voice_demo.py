#!/usr/bin/env python3
"""
情感语气演示脚本

展示 CosyVoice2 在同一段台词下，不同情感语气的效果对比。
角色设定：中年男性（如小说中的郡守、将领、重臣）

运行方式：
    # 需要先启动 CosyVoice2 Docker 服务（见 docker-compose.yml）
    python emotion_voice_demo.py

    # 或指定 HTTP 服务地址
    python emotion_voice_demo.py --url http://localhost:50000

    # 仅打印 instruct 指令（不实际合成，用于验证映射逻辑）
    python emotion_voice_demo.py --dry-run
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

from cosyvoice_tts import (
    CosyVoice2TTS,
    Emotion,
    EMOTION_INSTRUCT_MAP,
    build_instruct_text,
    detect_emotion,
    save_wav,
)


# ---------------------------------------------------------------------------
# 演示场景定义
# ---------------------------------------------------------------------------

# 角色设定：中年男性，郡守黑夫（《秦吏》第300章）
CHARACTER = {
    "name":          "黑夫",
    "age_stage":     "中年",
    "gender":        "男",
    "temperament":   "老成持重，威严从容",
    "voice_desc":    "声音浑厚低沉，带有久居上位者的沉稳",
}

# 同一句台词，用不同情感演绎
BASE_LINE = "诸位，这件事本官已经知道了，你们都先退下。"

# 每种情感的演示场景说明
EMOTION_SCENARIOS = [
    {
        "emotion":   Emotion.ANXIOUS,
        "scene":     "前线战报突至，敌军逼近",
        "text":      "快去叫副将！敌军已过了渭水，现在就走！",
    },
    {
        "emotion":   Emotion.RELAXED,
        "scene":     "太平盛世，与旧友饮酒叙旧",
        "text":      "来来来，今日不谈公事，咱们就说说当年在军中的那些趣事。",
    },
    {
        "emotion":   Emotion.LOW_DEEP,
        "scene":     "朝堂宣判，处置叛将",
        "text":      "此人通敌叛国，罪证确凿。依律，诛九族。",
    },
    {
        "emotion":   Emotion.EXCITED,
        "scene":     "北击匈奴大胜，凯旋入城",
        "text":      "我们赢了！二十年了，匈奴终于退出了河南地！兄弟们，你们是大秦的英雄！",
    },
    {
        "emotion":   Emotion.ANGRY,
        "scene":     "发现下属中饱私囊，克扣军饷",
        "text":      "你还有脸来见我！那是将士们的血汗钱！你给我跪下！",
    },
    {
        "emotion":   Emotion.SAD,
        "scene":     "挚友战场阵亡，亲自祭奠",
        "text":      "老东陵……你走得太早了。当年我们一起在云梦泽许下的誓言，还没来得及实现啊。",
    },
    {
        "emotion":   Emotion.CALM,
        "scene":     "例行公事，批阅文书",
        "text":      BASE_LINE,
    },
    {
        "emotion":   Emotion.SOLEMN,
        "scene":     "始皇帝驾崩，主持哀悼仪式",
        "text":      "陛下驾崩，举国同悲。百官肃立，向陛下行最后的礼。",
    },
]


# ---------------------------------------------------------------------------
# 从 LLM 画像自动推断的演示
# ---------------------------------------------------------------------------

# 模拟 LLM 对不同章节输出的 emotional_state
LLM_PROFILE_EXAMPLES = [
    {"chapter": 100, "emotional_state": "豪情万丈，战意旺盛，略带紧张",  "text": "全军冲锋！"},
    {"chapter": 300, "emotional_state": "老成持重，有些疲惫但仍从容",    "text": "诸位父老，黑夫此来，为的是与诸位一同建设南郡。"},
    {"chapter": 500, "emotional_state": "深沉而感慨，有对岁月流逝的悲叹", "text": "人生如白驹过隙，但能为这大秦留下些什么，也不枉此生了。"},
    {"chapter": 700, "emotional_state": "悲伤痛苦，老泪纵横",            "text": "陛下……您走好。"},
]


def print_separator(title: str = ""):
    width = 70
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * pad}")
    else:
        print("─" * width)


def demo_dry_run():
    """仅打印 instruct 指令，不调用 TTS 服务（用于验证映射逻辑）。"""
    print_separator("情感 → instruct_text 映射预览")
    print(f"{'情感':<8} {'instruct_text'}")
    print("─" * 70)
    for emotion in Emotion:
        instruct = build_instruct_text(emotion, age_stage="中年")
        print(f"{emotion.value:<8} {instruct}")

    print_separator("LLM emotional_state → 自动推断情感")
    print(f"{'emotional_state':<25} {'推断情感':<8} {'instruct_text'}")
    print("─" * 70)
    for example in LLM_PROFILE_EXAMPLES:
        emotion = detect_emotion(example["emotional_state"])
        instruct = build_instruct_text(emotion, age_stage="中年")
        print(f"{example['emotional_state']:<25} {emotion.value:<8} {instruct}")

    print_separator("演示场景（需 --no-dry-run 才实际合成）")
    for s in EMOTION_SCENARIOS:
        instruct = build_instruct_text(s["emotion"], age_stage="中年")
        print(f"\n[{s['emotion'].value}] 场景：{s['scene']}")
        print(f"  台词：{s['text']}")
        print(f"  指令：{instruct}")


def demo_synthesis(tts: CosyVoice2TTS, output_dir: str):
    """实际调用 TTS 服务合成各情感语音。"""
    os.makedirs(output_dir, exist_ok=True)

    print_separator(f"角色：{CHARACTER['name']} | {CHARACTER['age_stage']}男性")
    print(f"  性格：{CHARACTER['temperament']}")
    print(f"  音色：{CHARACTER['voice_desc']}")

    # 1. 各情感场景演示
    print_separator("场景演示：同一角色的 8 种情感语气")

    results_summary = []
    for i, scenario in enumerate(EMOTION_SCENARIOS, 1):
        emotion = scenario["emotion"]
        text = scenario["text"]
        scene = scenario["scene"]

        print(f"\n[{i}/{len(EMOTION_SCENARIOS)}] {emotion.value} - {scene}")
        print(f"  台词：{text}")

        instruct = build_instruct_text(emotion, age_stage="中年")
        print(f"  指令：{instruct}")

        try:
            result = tts.synthesize(
                text=text,
                emotion=emotion,
                spk_id="中文男",
                age_stage="中年",
            )
            filename = f"{i:02d}_{emotion.value}.wav"
            filepath = os.path.join(output_dir, filename)
            save_wav(result, filepath)
            print(f"  合成耗时：{result.latency_seconds:.2f}s | 音频时长：{result.duration_seconds:.1f}s")
            results_summary.append({"emotion": emotion.value, "file": filename, "ok": True})
        except Exception as e:
            print(f"  合成失败：{e}")
            results_summary.append({"emotion": emotion.value, "file": "", "ok": False})

    # 2. LLM 画像自动推断演示
    print_separator("自动推断：LLM 画像 → 情感 → 语音")

    for example in LLM_PROFILE_EXAMPLES:
        emotion = detect_emotion(example["emotional_state"])
        print(f"\n  第{example['chapter']}章 | LLM状态：{example['emotional_state']}")
        print(f"  → 推断情感：{emotion.value}")
        print(f"  → 台词：{example['text']}")

        try:
            result = tts.synthesize_for_character(
                text=example["text"],
                age_stage="中年",
                gender="男",
                emotional_state=example["emotional_state"],
                temperament=CHARACTER["temperament"],
            )
            filename = f"llm_ch{example['chapter']}_{emotion.value}.wav"
            filepath = os.path.join(output_dir, filename)
            save_wav(result, filepath)
            print(f"  → 合成耗时：{result.latency_seconds:.2f}s | 音频：{filename}")
        except Exception as e:
            print(f"  → 合成失败：{e}")

    # 汇总
    print_separator("合成结果汇总")
    ok_count = sum(1 for r in results_summary if r["ok"])
    print(f"成功：{ok_count}/{len(results_summary)}")
    print(f"输出目录：{os.path.abspath(output_dir)}")
    for r in results_summary:
        status = "✓" if r["ok"] else "✗"
        print(f"  {status} {r['emotion']:<8}  {r['file']}")


def main():
    parser = argparse.ArgumentParser(description="CosyVoice2 情感语气演示")
    parser.add_argument("--url",     default="http://localhost:50000", help="CosyVoice2 HTTP 服务地址")
    parser.add_argument("--model",   default="pretrained_models/CosyVoice2-0.5B", help="本地模型路径（SDK模式）")
    parser.add_argument("--output",  default="output_emotion_demo", help="音频输出目录")
    parser.add_argument("--dry-run", action="store_true", help="仅打印指令映射，不合成")
    args = parser.parse_args()

    if args.dry_run:
        demo_dry_run()
        return

    tts = CosyVoice2TTS(http_url=args.url, sdk_model_dir=args.model)

    print("=" * 70)
    print("  CosyVoice2 情感语气演示")
    print("  角色：中年男性（以《秦吏》郡守黑夫为原型）")
    print("=" * 70)

    print("\n正在连接 CosyVoice2 服务...")
    try:
        tts._init_backend()
        print(f"后端：{tts._backend}")
    except RuntimeError as e:
        print(f"\n错误：{e}")
        print("\n提示：使用 --dry-run 参数可在不启动服务的情况下预览指令映射。")
        sys.exit(1)

    demo_synthesis(tts, args.output)


if __name__ == "__main__":
    main()
