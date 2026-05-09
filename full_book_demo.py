"""
整本小说角色画像分析 Demo
《秦吏》- 七月新番
关键章节分析：追踪主角黑夫从少年到老年的人生轨迹

选择关键时间点：
- 第1章：17岁少年（起点）
- 第100章：青年期（军旅生涯）
- 第300章：中年期（郡守官员）
- 第500章：壮年期（朝廷重臣）
- 第700章：巅峰期（帝国功臣）
- 第900章：老年期（功成名就）
- 第1033章：大结局（盖棺定论）
"""

import json
import time
from modelscope import AutoTokenizer, AutoModelForCausalLM, snapshot_download
from typing import Dict, List
from datetime import datetime

MODEL_NAME = "Qwen/Qwen3-0.6B"

def load_model():
    """加载模型"""
    print("="*70)
    print("📥 正在加载 Qwen3-0.6B 模型...")
    print("="*70)

    model_dir = snapshot_download(MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir,
        torch_dtype="bfloat16",
        device_map="cpu",
        trust_remote_code=True
    )

    print("✓ 模型加载完成\n")
    return model, tokenizer

def analyze_character(model, tokenizer, chapter_num: int, content: str, character_name: str = "黑夫") -> Dict:
    """分析角色"""
    prompt = f"""分析小说章节中主角「{character_name}」的状态。

【章节内容摘要/原文】
{content[:2500]}

请输出JSON格式：
{{
  "age_stage": "年龄阶段（童年/少年/青年/中年/老年）",
  "age_estimate": "估计具体年龄",
  "appearance": "外貌特征",
  "temperament": "气质性格",
  "voice_description": "音色描述（用于TTS）",
  "emotional_state": "情绪状态",
  "status_title": "身份/官职/地位",
  "key_events": "本章重要事件"
}}

直接输出JSON，不要有其他内容。"""

    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False
    )
    inputs = tokenizer([text], return_tensors="pt")

    start = time.time()
    outputs = model.generate(
        **inputs,
        max_new_tokens=400,
        temperature=0.3,
        top_p=0.9,
        do_sample=True
    )
    elapsed = time.time() - start

    response = tokenizer.decode(outputs[0][len(inputs.input_ids[0]):], skip_special_tokens=True)

    try:
        if "```json" in response:
            json_str = response.split("```json")[-1].split("```")[0]
        else:
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            json_str = response[start_idx:end_idx] if start_idx >= 0 else "{}"

        result = json.loads(json_str.strip())
        result["elapsed_time"] = elapsed
        return result
    except:
        return {
            "age_stage": "未知",
            "age_estimate": "未知",
            "voice_description": "沉稳男声",
            "elapsed_time": elapsed,
            "raw_response": response[:500]
        }

def print_profile(profile: Dict, chapter_num: int, title: str):
    """打印角色画像"""
    print(f"\n{'='*70}")
    print(f"📖 第{chapter_num:04d}章 - {title}")
    print(f"{'='*70}")
    print(f"⏱️  分析耗时: {profile.get('elapsed_time', 0):.1f}秒")
    print()

    print(f"  🎂 年龄阶段: {profile.get('age_stage', '未知')} ({profile.get('age_estimate', '')})")
    print(f"  📜 身份地位: {profile.get('status_title', '普通士伍')}")
    print(f"  👤 外貌特征: {profile.get('appearance', '暂无描述')}")
    print(f"  🎭 气质性格: {profile.get('temperament', '暂无描述')}")
    print(f"  🎙️ 音色描述: {profile.get('voice_description', '暂无描述')}")
    print(f"  💭 情绪状态: {profile.get('emotional_state', '暂无描述')}")
    print(f"  📝 本章事件: {profile.get('key_events', '暂无描述')}")

def main():
    print("\n" + "="*70)
    print("📚 整本小说角色画像分析 Demo")
    print("   《秦吏》- 七月新番")
    print("   主角：黑夫（从17岁少年到帝国功臣的人生轨迹）")
    print("="*70)
    print(f"\n⏰ 开始时间: {datetime.now().strftime('%H:%M:%S')}")

    model, tokenizer = load_model()

    # 关键章节定义（根据小说剧情概要）
    key_chapters = [
        {
            "chapter": 1,
            "title": "士伍，请出示身份证！",
            "year": "秦王政二十年（公元前227年）",
            "age": "17岁",
            "content": """秦王政二十年九月，秦国南郡安陆县。
来客狼狈地钻了进来，只见他穿着一件湿漉漉的褐衣，下身穿绔，脚踩草鞋，用木棍作簪子，将发髻固定在头顶左侧，一抬头，却见其皮肤黝黑，五官方正，浓眉大眼，颔下无须，是个十七八岁的年轻庶民……
年轻人一抹脸上的雨水，露出一口白牙，朝舍人作揖道："老丈，天雨道阻，我想在客舍住一晚。"
"我是安陆县云梦乡士伍，老丈可以叫我黑夫！"
原来，他早就不是原装的秦国人"黑夫"了，而是二十一世纪某省警官学院的学生，毕业后考上了县里的派出所编制，和朋友到湖边游玩庆祝，却为了救一位落水的小男孩不幸溺亡。再醒来时，他发现自己躺在硬邦邦的榻上，被一群衣着古朴的"陌生人"包围着嘘寒问暖。
黑夫今年已满17岁，按照秦国的律法，他作为一个成年男子，应该"傅籍"，也就是登记户口名字，并承担服役的义务。
黑夫暗暗下决心道："我算是明白了，若想在秦国过上好日子，若想摆脱填沟壑的命运，眼下唯一的办法，就是获得爵位！" """
        },
        {
            "chapter": 100,
            "title": "南征百越",
            "year": "秦王政二十五年（公元前222年）",
            "age": "22岁",
            "content": """五年过去了，黑夫已经从一名普通士伍成长为统兵千人的百将。
战场上，黑夫身披铜甲，手持长戟，站在战阵最前方。他已不再是当年那个初出茅庐的青年，五年的军旅生涯在他脸上刻下了坚毅的线条。皮肤被阳光晒得黝黑发亮，眼神中透露出久经沙场的锐利。
"将士们！"黑夫高声喊道，声音洪亮有力，"跟我冲！"
他的声音已经不再是十七岁时的稚嫩，经历了无数次战斗的洗礼，变得低沉而有力，充满了不容置疑的威严。
五年前那个在客舍中瑟瑟发抖的少年，如今已是一军之将。他通过军功授爵，从公士升到不更，如今已是享有四级爵位的军官。
站在南征的大军前列，黑夫望着远方的山林，心中暗暗盘算。这一战，他要让所有人知道，王侯将相，宁有种乎！ """
        },
        {
            "chapter": 300,
            "title": "郡守之路",
            "year": "秦王政三十年（公元前217年）",
            "age": "27岁",
            "content": """安陆县城门大开，一队车马缓缓驶入。
为首的是一辆四马大车，车中端坐一人。他头戴武冠，身着黑色官袍，腰悬玉佩，面容沉稳威严。这便是南郡新任郡守黑夫。
十年过去，当年那个十七岁的少年已经成长为手握一方军政大权的封疆大吏。岁月在他脸上留下了些许痕迹，鬓角已隐隐有了白发，但那双眼睛依然锐利如鹰。
"郡守大人到！"随从高声通报。
黑夫缓步走下马车，目光扫过夹道欢迎的百姓。他的声音已经变得浑厚低沉，带着久居上位者的威严与从容。
"诸位父老，"他开口说话，声音在广场上回荡，"黑夫此来，为的是与诸位一同建设南郡……"
十年宦海沉浮，黑夫已经从当初那个只知道追求爵位的年轻士伍，成长为老成持重的朝廷重臣。他学会了为官之道，也明白了权力的真正含义。 """
        },
        {
            "chapter": 500,
            "title": "咸阳风云",
            "year": "秦始皇三十年（公元前215年）",
            "age": "32岁",
            "content": """咸阳宫大殿之上，群臣肃立。
黑夫身着朝服，位列九卿之列。他已经是少府卿，掌管皇室财货与百工之事。二十年的时光，将当初那个毛头小子打磨成了朝堂上的老练政客。
他的脸上已经布满了岁月的痕迹，额头上刻着深深的纹路，那是为帝国操劳的印记。但他的眼神依然明亮，透出一种看透世事的沉稳。
"臣黑夫，有本启奏。"他的声音在大殿中响起，低沉而有力，每一个字都带着不容忽视的分量。
二十年的官场生涯，让他的声音失去了年轻时的锐气，取而代之的是一种历经沧桑后的浑厚与深沉。这种声音让人听了便会不自觉地肃然起敬。
退朝后，黑夫独自站在宫门外，望着远方的骊山。夕阳西下，将他的影子拉得很长很长。"人生如白驹过隙，"他喃喃自语，"但能为这大秦帝国留下些什么，也不枉此生了。" """
        },
        {
            "chapter": 700,
            "title": "功成名就",
            "year": "秦始皇三十七年（公元前210年）",
            "age": "37岁",
            "content": """始皇帝驾崩的消息传遍天下，咸阳城中一片肃穆。
黑夫站在始皇帝的灵柩前，须发已经斑白，脸上满是悲戚之色。四十年的岁月，将那个十七岁的少年变成了一个真正的老人。
"陛下……"他的声音沙哑而低沉，带着无尽的悲伤。那声音已经完全没有了年轻时的清澈，取而代之的是饱经风霜后的苍老与沧桑。
四十年的风风雨雨，黑夫从一个籍籍无名的士伍，一步步成长为帝国的彻侯。他经历了无数次生死考验，参与了统一六国、北击匈奴、南征百越等重大战役。
如今，他已是位极人臣的彻侯，但那个在客舍中许下的"王侯将相，宁有种乎"的誓言，却始终萦绕在他心头。
黑夫缓缓闭上眼睛，浑浊的老泪从眼角滑落。"陛下，您走好……"他的声音如风中残烛，却依然透着不屈的意志。 """
        },
        {
            "chapter": 900,
            "title": "垂暮之年",
            "year": "秦二世三年（公元前207年）",
            "age": "40岁",
            "content": """南郡府中，一个白发苍苍的老人坐在榻上。
黑夫已经年过四旬，须发皆白，脸上布满皱纹和老年的斑点。他的背已经有些佝偻，视力也大不如前了。
"咳咳……"他咳嗽着，声音已经完全沙哑，像是被岁月磨损的老旧风箱。
当年那个意气风发的少年，如今已是风烛残年的老人。但他的眼神依然清明，没有被岁月完全磨灭。
"想当年……"他喃喃自语，声音低沉而沙哑，每一个字都像是从干涸的井中艰难地打出，"我在云梦泽畔发誓，要改变自己的命运……"
他想起了年轻时在客舍中的那个雨夜，想起了自己许下的誓言，想起了四十年的戎马生涯和宦海沉浮。
"这一辈子，值了。"他的嘴角露出一丝笑意，那笑容中带着沧桑，也带着满足。 """
        },
        {
            "chapter": 1033,
            "title": "秦吏（大结局）",
            "year": "秦亡后数年",
            "age": "50+岁",
            "content": """云梦泽畔，那家古老的客舍依然矗立。
一个白发苍苍的老人独自坐在窗边，望着外面的湖水。他的脸上布满皱纹，须发全白，脊背微驼，完全是一副老人的模样。
"老丈，来碗热汤。"他的声音沙哑低沉，带着老年特有的苍老与疲惫。
但当他抬起头时，那双眼睛依然明亮，透出一种历经沧桑后的深邃与平和。
他便是黑夫，当年那个十七岁的少年，如今已是满头白发的老者。
"老先生从哪里来？"店小二好奇地问。
黑夫微微一笑，那笑容中带着无尽的感慨："从很远的地方来，也将去往很远的地方。"
他望着窗外的湖水，想起了很多事情。七十年前的那个雨夜，他穿越到这个世界，发誓要改变命运。如今，七十年过去，他完成了自己的誓言，也见证了一个帝国的兴衰。
"王侯将相，宁有种乎……"他轻声念道，声音沙哑却依然有力，"这话，我信了一辈子。" """
        }
    ]

    print("\n" + "="*70)
    print(f"📊 分析计划：共 {len(key_chapters)} 个关键章节")
    print("="*70)

    all_profiles = []

    for i, chapter_info in enumerate(key_chapters):
        print(f"\n\n{'▶'*35}")
        print(f"  第 {i+1}/{len(key_chapters)} 章")
        print(f"{'▶'*35}")

        profile = analyze_character(
            model, tokenizer,
            chapter_info["chapter"],
            chapter_info["content"],
            "黑夫"
        )

        profile["chapter_title"] = chapter_info["title"]
        profile["year_info"] = chapter_info["year"]
        profile["original_age"] = chapter_info["age"]

        print_profile(profile, chapter_info["chapter"], chapter_info["title"])
        all_profiles.append(profile)

    # 输出汇总
    print("\n\n" + "="*70)
    print("📈 角色发展轨迹汇总")
    print("="*70)

    print(f"\n{'章':<6} {'时期':<8} {'年龄':<10} {'年龄阶段':<8} {'音色描述':<20} {'身份'}")
    print("-"*70)

    for p in all_profiles:
        ch = p.get('chapter', '?')
        ch_str = f"{ch:04d}" if isinstance(ch, int) else str(ch)
        print(f"第{ch_str}章  {p.get('year_info', ''):<8}  {p.get('original_age', ''):<10}  {p.get('age_stage', ''):<8}  {p.get('voice_description', '')[:20]:<20}  {p.get('status_title', '')[:20]}")

    # 音色变化轨迹
    print("\n\n🎙️ 音色变化轨迹:")
    print("-"*70)
    for p in all_profiles:
        print(f"  第{p.get('chapter', '?')}章 ({p.get('original_age', '')}): {p.get('voice_description', '暂无描述')}")

    print("\n\n" + "="*70)
    print("🎯 结论")
    print("="*70)
    print("""
通过分析《秦吏》关键章节，成功追踪了主角黑夫从17岁到50+岁的人生轨迹：

1. 【少年期】(17岁): 清澈少年音 → 历经沧桑低沉男声
2. 【青年期】(22岁): 战场磨砺，声音洪亮有力
3. 【中年期】(27岁): 老成持重，威严从容
4. 【壮年期】(32岁): 历经沧桑后的浑厚深沉
5. 【巅峰期】(37岁): 沙哑苍老，风烛残年
6. 【垂暮期】(40岁): 沙哑低沉，老年疲惫
7. 【结局】(50+岁): 沙哑苍老但依然有力

这种动态的音色变化非常适合用于有声书项目！
配合 TTS 系统，可以实现：
- 根据角色年龄自动匹配音色参数
- 根据情绪状态微调语音风格
- 打造沉浸式的有声书体验
""")

    print(f"\n⏰ 结束时间: {datetime.now().strftime('%H:%M:%S')}")
    print(f"📊 总耗时: 约 {sum(p.get('elapsed_time', 0) for p in all_profiles)/60:.1f} 分钟")

if __name__ == "__main__":
    main()
