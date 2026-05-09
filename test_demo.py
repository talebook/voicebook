"""
测试脚本：基于 Qwen3-0.6B 的小说角色文本画像识别
小说：《秦吏》- 七月新番
"""
import json
import requests
import time
import sys
from typing import Dict, List

OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen3:0.6b"

CHAPTER_1_CONTENT = """秦王政二十年（公元前227年）九月，秦国南郡安陆县，傍晚时分，云梦泽畔下起了雨，激起湖水涟漪阵阵，打得芭蕉七零八落，只有那些落到客舍屋顶上的，才不甘地被瓦片挡住。

湖边一家简陋的客舍内，鬓角发白的"舍人"，也就是店主人，正哼着楚地歌谣忙里忙外，却听到外边传来一阵狗吠，接着是沉重的敲门声。

"这么晚还有人来。"他骂了一句，才慢吞吞地挪过去打开门。

来客狼狈地钻了进来，只见他穿着一件湿漉漉的褐衣，下身穿绔，脚踩草鞋，用木棍作簪子，将发髻固定在头顶左侧，一抬头，却见其皮肤黝黑，五官方正，浓眉大眼，颔下无须，是个十七八岁的年轻庶民……

年轻人一抹脸上的雨水，露出一口白牙，朝舍人作揖道："老丈，天雨道阻，我想在客舍住一晚。"

年轻人埋头在褡裢里掏了掏，将杨木板制成的"验"，以及柳木条削成的"传"小心取出，双手交给舍人，同时介绍起自己来。

"我是安陆县云梦乡士伍，老丈可以叫我黑夫！"

原来，他早就不是原装的秦国人"黑夫"了，而是二十一世纪某省警官学院的学生，毕业后考上了县里的派出所编制，和朋友到湖边游玩庆祝，却为了救一位落水的小男孩不幸溺亡。再醒来时，他发现自己躺在硬邦邦的榻上，被一群衣着古朴的"陌生人"包围着嘘寒问暖。后来才知道，这是他的母亲、哥哥、弟弟等。自己大概是遭遇了小说里名为"穿越"的烂俗桥段，而且还一口气回到了两千多年前，成了名叫"黑夫"的秦国安陆县青年！

黑夫今年已满17岁，按照秦国的律法，他作为一个成年男子，应该"傅籍"，也就是登记户口名字，并承担服役的义务。

黑夫向家里要的衣服和钱寄到没有，后世不得而知，但有一点是考古学家肯定的：在发掘过程中，墓里只有这封信而没有黑夫的遗骨，也就是说，黑夫很可能死在秦灭楚的战争中，只留下了这封信，被家人作为一个念想带入墓葬里……

黑夫开始绞尽脑汁，如何才能避免日后战死的命运。他的大哥"衷"听了他的担忧后哈哈大笑，解答了黑夫的疑虑。秦国在这方面还是考虑很周全的，作为人生第一次服役，黑夫只需到安陆县城当一个月的"更卒"，帮公家修城站岗，或是接受军事训练，不会上战场的，黑夫这才松了口气。

黑夫找了个舒服的姿势盘腿坐下，一边烤着衣服，一边打量同一屋檐下的几人。其中一个瘦猴般的青年更是热络地招呼道："小兄弟，来这坐。"那人名叫"季婴"，他忽然压低了声音，对黑夫等人道：

"我听关中来的人说，上个月，有个燕国刺客，竟敢在咸阳宫殿里行刺大王！"

黑夫认真听着，他不像季婴一般愤世嫉俗，而是默默坐下，从褡裢里取出母亲为他准备的食物。他暗暗下决心道："我算是明白了，若想在秦国过上好日子，若想摆脱填沟壑的命运，眼下唯一的办法，就是获得爵位！"
"""

def check_ollama_health():
    """检查 Ollama 服务状态"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            print(f"✓ Ollama 服务正常")
            print(f"  已加载模型数量: {len(models)}")
            for model in models:
                print(f"  - {model.get('name', 'unknown')}")
            return True
    except requests.exceptions.ConnectionError:
        print("✗ Ollama 服务未启动，请先运行: docker-compose up -d")
        return False
    except Exception as e:
        print(f"✗ Ollama 检查失败: {e}")
        return False
    return False

def pull_model():
    """拉取 Qwen3:0.6b 模型"""
    print(f"\n正在拉取模型 {MODEL_NAME}...")
    print("  (首次使用需要下载约 523MB，可能需要几分钟...)")

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/pull",
            json={"name": MODEL_NAME},
            stream=True,
            timeout=600
        )

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line)
                    if "status" in data:
                        print(f"  {data['status']}")
                    if data.get("success"):
                        print(f"✓ 模型下载完成!")
                        return True
                except:
                    pass

        return True
    except Exception as e:
        print(f"✗ 模型拉取失败: {e}")
        return False

def analyze_character(chapter_num: int, content: str, character_name: str, previous_info: str = None):
    """分析角色画像"""
    prompt = f"""分析以下小说章节中角色「{character_name}」的状态。

【章节内容】
{content[:3500]}

【分析要求】
请从以下维度分析该角色在当前章节的状态，用JSON格式输出：
- age_stage: 年龄阶段（童年/少年/青年/中年/老年）
- appearance: 外貌特征描述
- temperament: 气质/性格特征
- voice_description: 音色描述（用于TTS语音合成）
- emotional_state: 当前情绪状态
- key_changes: 与之前相比的重要变化（如有）

直接输出JSON，不要有其他内容。"""

    if previous_info:
        prompt += f"\n\n【角色过往状态（参考）】\n{previous_info}"

    try:
        start_time = time.time()
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 300,
                }
            },
            timeout=180
        )

        elapsed = time.time() - start_time

        if response.status_code == 200:
            result = response.json()
            return result.get("response", ""), elapsed
        else:
            return f"Error: {response.status_code}", 0

    except requests.exceptions.Timeout:
        return "Error: 请求超时", 180
    except Exception as e:
        return f"Error: {str(e)}", 0

def parse_json_response(response_text: str) -> dict:
    """解析 LLM 返回的 JSON"""
    import json

    text = response_text.strip()

    if "```json" in text:
        text = text.split("```json")[-1].split("```")[0]
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            text = parts[1]
        else:
            text = text.replace("```", "")

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                try:
                    return json.loads(line)
                except:
                    pass
            if ':' in line and '"' in line:
                try:
                    start = text.find('{')
                    end = text.rfind('}') + 1
                    if start >= 0 and end > start:
                        return json.loads(text[start:end])
                except:
                    pass

        return {"error": "无法解析响应", "raw": response_text[:500]}

def print_profile(profile: dict, character_name: str, chapter: int, elapsed: float):
    """格式化打印角色画像"""
    print(f"\n{'='*60}")
    print(f"📖 章节 {chapter} - 角色「{character_name}」画像")
    print(f"{'='*60}")
    print(f"⏱️  分析耗时: {elapsed:.1f}秒")
    print()

    if "error" in profile and "raw" in profile:
        print("❌ 解析失败，原文如下:")
        print(profile["raw"])
        return

    fields = [
        ("age_stage", "🎂 年龄阶段"),
        ("appearance", "👤 外貌特征"),
        ("temperament", "🎭 气质性格"),
        ("voice_description", "🎙️ 音色描述"),
        ("emotional_state", "💭 情绪状态"),
        ("key_changes", "📝 重要变化"),
    ]

    for key, label in fields:
        value = profile.get(key, "未知")
        if value:
            print(f"{label}: {value}")

    print()
    print("="*60)

def main():
    print("\n" + "="*60)
    print("📚 小说角色文本画像识别测试")
    print(f"🤖 使用模型: {MODEL_NAME}")
    print("="*60)

    if not check_ollama_health():
        sys.exit(1)

    print("\n" + "-"*60)
    print("📖 测试小说：《秦吏》- 七月新番")
    print("-"*60)

    characters_to_analyze = ["黑夫", "季婴"]

    for char in characters_to_analyze:
        print(f"\n{'▶'*30}")
        print(f"正在分析角色: {char}")
        print(f"{'▶'*30}")

        response, elapsed = analyze_character(1, CHAPTER_1_CONTENT, char)

        if response.startswith("Error:"):
            print(f"\n❌ 分析失败: {response}")
            continue

        profile = parse_json_response(response)
        print_profile(profile, char, 1, elapsed)

    print("\n\n" + "="*60)
    print("🎯 测试完成!")
    print("="*60)

    print("\n💡 使用说明:")
    print("   - 修改 CHAPTER_1_CONTENT 和 characters_to_analyze 测试其他章节/角色")
    print("   - 可扩展为批量处理多章节，追踪角色变化")
    print("   - 配合 TTS 系统实现动态音色匹配")

if __name__ == "__main__":
    main()
