"""L3 角色画像：程序化（规则）从文本抽取 性别/年龄/音色线索，并映射到 TTS 音色

线索来源（全部显式文本，无LLM）：
  性别: 名字附近的性别名词、主语代词、引文称呼语（"项平哥"→男）
  年龄: 名字±窗口内 "N岁/十七八岁/四十多岁" 等模式；兜底用 少年/老者 等阶段词
  音色: 低沉/沙哑/尖锐/苍老 等描述词（出现在含名字的段落中）
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

CN_DIGIT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

FEMALE_NOUNS = "女孩|女子|少女|姑娘|女声|夫人|小姐|婶|姨娘|丫头|女童|老妪|妇人|姣好|肤白|白嫩|娇|裙|钗|妆|夫君"
MALE_NOUNS = "男孩|男子|少年郎|汉子|公子|男声|老汉|老者|大叔|小伙|男童|胡须|络腮"
FEMALE_CALL = "妹|姐|姑|婶|娘"
MALE_CALL = "哥|弟|叔|兄|爷"
STAGE_WORDS = {"童年": "孩童|小孩|稚童|女童|男童", "少年": "少年|少女|丫头",
               "青年": "青年|小伙|姑娘", "中年": "中年|大叔|妇人", "老年": "老者|老人|老汉|老妪|苍老"}
VOICE_DESC = "低沉|沙哑|尖锐|清脆|洪亮|苍老|冰冷|悦耳|稚嫩|浑厚|尖细|粗哑|柔和|清亮"

AGE_RE = re.compile(r"([一二两三四五六七八九十\d]{1,3})(?:[一二三四五六七八九\d])?(多|来|几)?岁")


def cn2int(s: str) -> Optional[int]:
    if s.isdigit():
        return int(s)
    if not s:
        return None
    # 处理 十一/二十三/四十 等
    total, cur = 0, 0
    for ch in s:
        v = CN_DIGIT.get(ch)
        if v is None:
            return None
        if v == 10:
            cur = (cur or 1) * 10
            total += cur
            cur = 0
        else:
            cur = v
    return total + cur if (total + cur) else None


def age_to_stage(age: int) -> str:
    if age <= 12:
        return "童年"
    if age <= 17:
        return "少年"
    if age <= 35:
        return "青年"
    if age <= 55:
        return "中年"
    return "老年"


@dataclass
class CharacterProfile:
    name: str
    gender: str = "unknown"      # male / female / unknown
    age: Optional[int] = None
    age_stage: str = "青年"      # 童年/少年/青年/中年/老年
    voice_desc: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)


def build_profiles(text: str, names: set) -> Dict[str, CharacterProfile]:
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    profiles = {n: CharacterProfile(n) for n in names}

    for name in names:
        p = profiles[name]
        f_votes = m_votes = 0
        stage_votes: Dict[str, int] = {}
        age_mentions: List[int] = []
        others = names - {name}

        def near(para, m, radius):
            """名字±radius 的窗口；若名字与线索之间隔着其他角色名则证据无效。"""
            w = para[max(0, m.start() - radius):m.end() + radius]
            return "" if any(o in w.replace(name, "") for o in others) else w

        for para in paras:
            for m in re.finditer(re.escape(name), para):
                window = para[max(0, m.start() - 30):m.end() + 30]
                # 性别证据用小窗口（±12），且中间不能隔着别的角色名
                gw = near(para, m, 12)
                f_votes += 3 * len(re.findall(FEMALE_NOUNS, gw))
                m_votes += 3 * len(re.findall(MALE_NOUNS, gw))
                f_votes += len(re.findall(r"她", gw))
                m_votes += len(re.findall(r"他", gw))
                # 年龄："十三岁的李项平" / "十几岁" / "四十多岁"，收集全部证据
                for am in AGE_RE.finditer(window):
                    age = cn2int(am.group(1))
                    if age:
                        if am.group(2):  # 多/来/几 → 加半档
                            age += 5
                        if 3 <= age <= 99:
                            age_mentions.append(age)
                            p.evidence.append(window.strip()[:40])
                # 年龄阶段词
                for stage, words in STAGE_WORDS.items():
                    c = len(re.findall(words, window))
                    if c:
                        stage_votes[stage] = stage_votes.get(stage, 0) + c
                # 音色描述词
                for d in re.findall(VOICE_DESC, window):
                    if d not in p.voice_desc:
                        p.voice_desc.append(d)
        # 称呼语（最强证据）："项平哥" → 李项平是男性
        tail = name[-2:]
        f_votes += 10 * len(re.findall(rf"{re.escape(tail)}[{FEMALE_CALL}]", text))
        m_votes += 10 * len(re.findall(rf"{re.escape(tail)}[{MALE_CALL}]", text))
        # 名字自带辈分（田叔/王婆）
        if name[-1] in "叔伯婶姨":
            stage_votes["中年"] = stage_votes.get("中年", 0) + 2
        elif name[-1] in "爷婆翁媪":
            stage_votes["老年"] = stage_votes.get("老年", 0) + 2
        if name[-1] in "婶姨婆媪娘":
            f_votes += 10
        elif name[-1] in "叔伯爷翁":
            m_votes += 10

        p.gender = "female" if f_votes > m_votes else "male" if m_votes > f_votes else "unknown"
        if age_mentions:  # 多处提及取中位数，抗"十几岁左右"这类粗略描述
            p.age = sorted(age_mentions)[len(age_mentions) // 2]
        if p.age is not None:
            p.age_stage = age_to_stage(p.age)
        elif stage_votes:
            p.age_stage = max(stage_votes, key=stage_votes.get)
    return profiles


# ---------- 画像 → edge-tts 音色 ----------

NARRATOR = ("zh-CN-YunjianNeural", "+0%", "+0Hz")  # 旁白：沉稳男声
# (gender, stage) → (voice, rate, pitch)
VOICE_BUCKETS = {
    ("male", "童年"): ("zh-CN-YunxiaNeural", "+0%", "+15Hz"),
    ("male", "少年"): ("zh-CN-YunxiaNeural", "+0%", "+0Hz"),
    ("male", "青年"): ("zh-CN-YunxiNeural", "+0%", "+0Hz"),
    ("male", "中年"): ("zh-CN-YunyangNeural", "+0%", "-10Hz"),
    ("male", "老年"): ("zh-CN-YunyangNeural", "-10%", "-35Hz"),
    ("female", "童年"): ("zh-CN-XiaoyiNeural", "+0%", "+20Hz"),
    ("female", "少年"): ("zh-CN-XiaoyiNeural", "+0%", "+5Hz"),
    ("female", "青年"): ("zh-CN-XiaoxiaoNeural", "+0%", "+0Hz"),
    ("female", "中年"): ("zh-CN-XiaoxiaoNeural", "+0%", "-20Hz"),
    ("female", "老年"): ("zh-CN-XiaoxiaoNeural", "-10%", "-40Hz"),
}
DEFAULT_BUCKET = ("zh-CN-YunxiNeural", "+0%", "+0Hz")  # 性别未知

AGE_STAGES = ("童年", "少年", "青年", "中年", "老年")

# 状态 → edge 韵律微调 (语速%差, 音高Hz差)；与年龄音色叠加
STATE_PROSODY = {
    "虚弱": (-12, -8), "愤怒": (+12, +12), "冷淡": (-4, -6),
    "低语": (-8, -8), "悲伤": (-10, -6), "急切": (+15, +4),
}
# 状态 → cosyvoice instruct 文本（worker 暂未接 instruct，预留）
STATE_INSTRUCT = {
    "虚弱": "用虚弱无力的语气", "愤怒": "用愤怒的语气", "冷淡": "用冷淡的语气",
    "低语": "用很小的声音轻声", "悲伤": "用悲伤的语气", "急切": "用急切快速的语气",
}


def _bump(token: str, suffix: str, delta: int) -> str:
    return f"{int(token.rstrip(suffix)) + delta:+d}{suffix}"


def apply_state(spec: tuple, state: str) -> tuple:
    """把发声状态叠加到音色规格上。edge(3元组)调韵律；cosy(2元组)暂原样返回(留待instruct)。"""
    if not state or not isinstance(spec, tuple) or len(spec) != 3:
        return spec
    voice, rate, pitch = spec
    dr, dp = STATE_PROSODY.get(state, (0, 0))
    return (voice, _bump(rate, "%", dr), _bump(pitch, "Hz", dp))


def assign_cosy_voices(profiles: Dict[str, CharacterProfile], bank: dict) -> Dict[str, tuple]:
    """每个角色 → (参考音频wav, 转写text)。按 (gender, age_stage) 匹配音色库。"""
    voices = {}
    entries = bank["voices"]
    for name, p in profiles.items():
        gender = p.gender if p.gender != "unknown" else "male"
        match = next((e for e in entries if e["gender"] == gender and p.age_stage in e["stages"]),
                     next((e for e in entries if e["gender"] == gender), entries[0]))
        voices[name] = (match["wav"], match["text"])
    return voices


def assign_voices(profiles: Dict[str, CharacterProfile]) -> Dict[str, tuple]:
    """每个角色 → (voice, rate, pitch)。同桶角色加确定性 pitch 偏移以示区分。"""
    bucket_used: Dict[tuple, int] = {}
    voices = {}
    for name in sorted(profiles):  # 排序保证可复现
        p = profiles[name]
        # 性别未知按男声处理（保留年龄段信息）
        gender = p.gender if p.gender != "unknown" else "male"
        voice, rate, pitch = VOICE_BUCKETS.get((gender, p.age_stage), DEFAULT_BUCKET)
        n = bucket_used.get((voice, pitch), 0)
        bucket_used[(voice, pitch)] = n + 1
        if n:  # 同桶第2、3人：±8Hz错开
            base = int(pitch.rstrip("Hz"))
            pitch = f"{base + (8 if n % 2 else -8) * ((n + 1) // 2):+d}Hz"
        voices[name] = (voice, rate, pitch)
    return voices
