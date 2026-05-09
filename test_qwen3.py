"""
小说角色文本画像识别测试
基于 Qwen3-0.6B 模型
直接使用 HuggingFace transformers 加载模型
"""
import json
import time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from typing import Dict, List

MODEL_NAME = "Qwen/Qwen3-0.6B"

CHAPTER_1_CONTENT = """秦王政二十年（公元前227年）九月，秦国南郡安陆县，傍晚时分，云梦泽畔下起了雨，激起湖水涟漪阵阵，打得芭蕉七零八落。

湖边一家简陋的客舍内，鬓角发白的"舍人"，也就是店主人，正哼着楚地歌谣忙里忙外，却听到外边传来一阵狗吠，接着是沉重的敲门声。

来客狼狈地钻了进来，只见他穿着一件湿漉漉的褐衣，下身穿绔，脚踩草鞋，用木棍作簪子，将发髻固定在头顶左侧，一抬头，却见其皮肤黝黑，五官方正，浓眉大眼，颔下无须，是个十七八岁的年轻庶民……

年轻人一抹脸上的雨水，露出一口白牙，朝舍人作揖道："老丈，天雨道阻，我想在客舍住一晚。"

年轻人介绍自己道："我是安陆县云梦乡士伍，老丈可以叫我黑夫！"

原来，他早就不是原装的秦国人"黑夫"了，而是二十一世纪某省警官学院的学生，毕业后考上了县里的派出所编制，和朋友到湖边游玩庆祝，却为了救一位落水的小男孩不幸溺亡。再醒来时，他发现自己躺在硬邦邦的榻上，被一群衣着古朴的"陌生人"包围着嘘寒问暖。自己大概是遭遇了小说里名为"穿越"的烂俗桥段，而且还一口气回到了两千多年前，成了名叫"黑夫"的秦国安陆县青年！

黑夫今年已满17岁，按照秦国的律法，他作为一个成年男子，应该"傅籍"，也就是登记户口名字，并承担服役的义务。

黑夫开始绞尽脑汁，如何才能避免日后战死的命运。他的大哥"衷"听了他的担忧后哈哈大笑，解答了黑夫的疑虑。秦国在这方面还是考虑很周全的，作为人生第一次服役，黑夫只需到安陆县城当一个月的"更卒"，帮公家修城站岗，或是接受军事训练，不会上战场的，黑夫这才松了口气。

屋内已有四五个人，正围着地灶烤火。其中一个瘦猴般的青年更是热络地招呼道："小兄弟，来这坐。"那人名叫"季婴"，他忽然压低了声音，对黑夫等人道：

"我听关中来的人说，上个月，有个燕国刺客，竟敢在咸阳宫殿里行刺大王！"

黑夫认真听着，他不像季婴一般愤世嫉俗，而是默默坐下，暗暗下决心道："我算是明白了，若想在秦国过上好日子，若想摆脱填沟壑的命运，眼下唯一的办法，就是获得爵位！"
"""

def load_model():
    """加载 Qwen3-0.6B 模型"""
    print("="*60)
    print("📥 正在加载模型...")
    print(f"   模型: {MODEL_NAME}")
    print("   首次运行需要下载约 1.3GB")
    print("="*60)

    start_time = time.time()

    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_NAME,
        trust_remote_code=True
    )

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.bfloat16,
        device_map="cpu",
        trust_remote_code=True
    )

    elapsed = time.time() - start_time
    print(f"✓ 模型加载完成，耗时 {elapsed:.1f}秒")
    print()

    return model, tokenizer

def analyze_character(
    model,
    tokenizer,
    chapter_num: int,
    content: str,
    character_name: str
) -> Dict:
    """分析角色画像"""
    prompt = f"""分析以下小说章节中角色「{character_name}」的状态。

【章节内容】
{content[:3000]}

【分析要求】
请从以下维度分析该角色在当前章节的状态，输出JSON格式：
{{
  "age_stage": "年龄阶段",
  "appearance": "外貌特征",
  "temperament": "气质性格",
  "voice_description": "音色描述（用于TTS）",
  "emotional_state": "情绪状态",
  "key_changes": "重要变化"
}}

直接输出JSON，不要有其他内容。"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    start_time = time.time()

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            temperature=0.3,
            top_p=0.9,
            do_sample=True
        )

    elapsed = time.time() - start_time

    response = tokenizer.decode(
        outputs[0][len(inputs.input_ids[0]):],
        skip_special_tokens=True
    )

    return response.strip(), elapsed

def parse_json_response(response_text: str) -> Dict:
    """解析 JSON 响应"""
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
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except:
                pass

        return {"error": "无法解析", "raw": response_text[:300]}

def print_profile(profile: Dict, character_name: str, chapter: int, elapsed: float):
    """打印角色画像"""
    print(f"\n{'='*60}")
    print(f"📖 章节 {chapter} - 角色「{character_name}」画像")
    print(f"{'='*60}")
    print(f"⏱️  分析耗时: {elapsed:.1f}秒")
    print()

    if "error" in profile:
        print("❌ 解析失败:")
        print(profile.get("raw", profile))
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

    model, tokenizer = load_model()

    print("\n" + "-"*60)
    print("📖 测试小说：《秦吏》- 七月新番")
    print("-"*60)

    characters_to_analyze = ["黑夫", "季婴"]

    for char in characters_to_analyze:
        print(f"\n{'▶'*30}")
        print(f"正在分析角色: {char}")
        print(f"{'▶'*30}")

        response, elapsed = analyze_character(
            model, tokenizer, 1, CHAPTER_1_CONTENT, char
        )

        if response.startswith("Error"):
            print(f"\n❌ 分析失败: {response}")
            continue

        profile = parse_json_response(response)
        print_profile(profile, char, 1, elapsed)

    print("\n\n" + "="*60)
    print("🎯 测试完成!")
    print("="*60)

    print("\n💡 扩展建议:")
    print("   1. 批量处理多章节，追踪角色年龄变化")
    print("   2. 与 TTS 系统集成，动态调整语音参数")
    print("   3. 存储角色画像历史，构建角色发展轨迹")

if __name__ == "__main__":
    main()
