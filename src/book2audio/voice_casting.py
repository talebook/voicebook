"""结构化音色目录与可复现的全书选角约束。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Iterable

from .script import ScriptChapter, ScriptCharacter


@dataclass(frozen=True)
class VoiceProfile:
    voice_id: str
    gender: str
    ages: tuple[str, ...]
    family: str = "standard"  # standard | dialect | overseas
    regions: tuple[str, ...] = ()
    descriptions: tuple[str, ...] = ()
    chinese_qa: bool = True


@dataclass
class CastAssignment:
    voice: str
    speed: float
    reasons: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)


def _voice(voice_id: str, gender: str, ages: str, **kwargs) -> VoiceProfile:
    return VoiceProfile(voice_id, gender, tuple(ages.split("/")), **kwargs)


QWEN_VOICES: tuple[VoiceProfile, ...] = (
    _voice("Cherry", "女", "青年", descriptions=("清亮",)),
    _voice("Serena", "女", "青年", descriptions=("柔和",)),
    _voice("Ethan", "男", "少年/青年", descriptions=("清亮",)),
    _voice("Chelsie", "女", "少年/青年"),
    _voice("Momo", "女", "少年/青年"),
    _voice("Vivian", "女", "青年", descriptions=("尖锐", "尖细")),
    _voice("Moon", "女", "青年", descriptions=("冰冷",)),
    _voice("Maia", "女", "青年/中年", descriptions=("悦耳",)),
    _voice("Kai", "男", "青年", descriptions=("柔和",)),
    _voice("Nofish", "男", "青年"),
    _voice("Bella", "女", "童年"),
    _voice("Katerina", "女", "中年/老年", descriptions=("低沉",)),
    _voice("Eldric Sage", "男", "老年", descriptions=("冰冷",)),
    _voice("Mia", "女", "少年"),
    _voice("Mochi", "男", "童年/少年"),
    _voice("Bellona", "女", "中年", descriptions=("洪亮", "浑厚")),
    _voice("Vincent", "男", "中年/老年", descriptions=("沙哑", "粗哑", "洪亮", "浑厚")),
    _voice("Bunny", "女", "童年", descriptions=("稚嫩",)),
    _voice("Neil", "男", "中年", descriptions=("沉稳", "清晰")),
    _voice("Elias", "男", "中年"),
    _voice("Arthur", "男", "老年", descriptions=("苍老",)),
    _voice("Nini", "女", "少年"),
    _voice("Ebona", "女", "老年", descriptions=("沙哑", "苍老")),
    _voice("Seren", "女", "中年/老年"),
    _voice("Pip", "男", "童年/少年", descriptions=("稚嫩", "尖细")),
    _voice("Stella", "女", "少年"),
    _voice("Andre", "男", "青年/中年", descriptions=("低沉", "克制")),
    _voice("Jada", "女", "青年/中年", family="dialect", regions=("上海", "江南")),
    _voice("Dylan", "男", "少年/青年", family="dialect", regions=("北京", "北方")),
    _voice("Li", "男", "青年/中年", family="dialect", regions=("南京", "江淮", "江南")),
    _voice("Marcus", "男", "中年/老年", family="dialect", regions=("陕西", "西北", "山区"), descriptions=("粗哑", "威严")),
    _voice("Roy", "男", "青年/中年", family="dialect", regions=("闽南", "福建", "台湾")),
    _voice("Peter", "男", "青年/中年", family="dialect", regions=("天津", "北方")),
    _voice("Eric", "男", "青年/中年", family="dialect", regions=("四川", "重庆", "西南", "山区")),
    _voice("Sunny", "女", "少年/青年", family="dialect", regions=("四川", "重庆", "西南", "山区")),
    _voice("Rocky", "男", "青年/中年", family="dialect", regions=("广东", "香港", "岭南"), descriptions=("粗哑",)),
    _voice("Kiki", "女", "少年/青年", family="dialect", regions=("广东", "香港", "岭南")),
    _voice("Aiden", "男", "青年", family="overseas", regions=("英语", "美国", "英国"), chinese_qa=False),
    _voice("Ryan", "男", "青年", family="overseas", regions=("英语", "美国", "英国"), chinese_qa=False),
    _voice("Jennifer", "女", "青年", family="overseas", regions=("英语", "美国", "英国"), chinese_qa=False),
    _voice("Bodega", "男", "青年/中年", family="overseas", regions=("西班牙", "拉美"), chinese_qa=False),
    _voice("Sonrisa", "女", "青年", family="overseas", regions=("西班牙", "拉美"), chinese_qa=False),
    _voice("Alek", "男", "青年/中年", family="overseas", regions=("俄罗斯",), chinese_qa=False),
    _voice("Dolce", "男", "青年", family="overseas", regions=("意大利",), chinese_qa=False),
    _voice("Lenn", "男", "青年", family="overseas", regions=("德国",), chinese_qa=False),
    _voice("Emilien", "男", "青年", family="overseas", regions=("法国",), chinese_qa=False),
    _voice("Radio Gol", "男", "中年", family="overseas", regions=("葡萄牙", "巴西"), chinese_qa=False),
    _voice("Ono Anna", "女", "青年", family="overseas", regions=("日本",), chinese_qa=False),
    _voice("Sohee", "女", "青年", family="overseas", regions=("韩国",), chinese_qa=False),
)


EDGE_VOICES: tuple[VoiceProfile, ...] = (
    _voice("zh-CN-YunjianNeural", "男", "中年/老年", descriptions=("沉稳", "旁白")),
    _voice("zh-CN-YunxiNeural", "男", "少年/青年"),
    _voice("zh-CN-YunxiaNeural", "男", "童年/少年"),
    _voice("zh-CN-YunyangNeural", "男", "青年/中年/老年", descriptions=("洪亮",)),
    _voice("zh-CN-XiaoxiaoNeural", "女", "青年/中年/老年", descriptions=("柔和",)),
    _voice("zh-CN-XiaoyiNeural", "女", "童年/少年/青年"),
    _voice("zh-CN-liaoning-XiaobeiNeural", "女", "青年/中年", family="dialect", regions=("东北", "北方")),
    _voice("zh-CN-shaanxi-XiaoniNeural", "女", "青年/中年", family="dialect", regions=("陕西", "西北", "山区")),
)


CATALOGS = {"qwen3tts": QWEN_VOICES, "edgetts": EDGE_VOICES}
DEFAULT_PROTAGONISTS = {
    "qwen3tts": {"男": "Andre", "女": "Serena"},
    "edgetts": {"男": "zh-CN-YunxiNeural", "女": "zh-CN-XiaoxiaoNeural"},
}
NON_HUMAN = {"机器人", "怪兽", "妖怪", "灵兽", "鬼魂", "神明", "其他非人类"}
AGE_ORDER = ("童年", "少年", "青年", "中年", "老年")
NON_HUMAN_AGE = {"幼体": "童年", "成年": "中年", "古老": "老年", "未知": "青年"}


def all_voice_ids(engine: str) -> set[str]:
    return {voice.voice_id for voice in CATALOGS[engine]}


def adjacency_graph(chapters: Iterable[ScriptChapter]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for chapter in chapters:
        previous: str | None = None
        for segment in chapter.segments:
            current = segment.character
            if current in {"旁白", "音", "?"}:
                continue
            if previous and previous != current:
                graph.setdefault(previous, set()).add(current)
                graph.setdefault(current, set()).add(previous)
            previous = current
    return graph


def _normalized_age(age: str) -> str:
    return NON_HUMAN_AGE.get(age, age if age in AGE_ORDER else "青年")


def _candidate_score(character: ScriptCharacter, voice: VoiceProfile) -> tuple[int, str]:
    age = _normalized_age(character.age_group)
    score = 0
    reasons: list[str] = []
    if character.gender in {"男", "女"} and voice.gender == character.gender:
        score += 40
    if age in voice.ages:
        score += 30
        reasons.append("年龄匹配")
    else:
        distance = min(abs(AGE_ORDER.index(age) - AGE_ORDER.index(item)) for item in voice.ages if item in AGE_ORDER)
        if distance == 1:
            score += 10
    region_hits = [region for region in voice.regions if region in character.region]
    if region_hits:
        score += 25
        reasons.append("地域匹配")
    description_hits = [item for item in voice.descriptions if item in character.voice_description]
    score += min(30, len(description_hits) * 10)
    if description_hits:
        reasons.append("音色描述匹配")
    if character.position == "旁白" and voice.voice_id in {"Neil", "Elias", "Arthur", "Seren", "zh-CN-YunjianNeural"}:
        score += 20
        reasons.append("讲述音")
    # 哈希只用于稳定打破完全同分，不受进程随机种子影响。
    tie = int(hashlib.sha256(f"{character.name}\0{voice.voice_id}".encode()).hexdigest()[:6], 16) % 1000
    return score * 1000 - tie, "、".join(reasons)


def _eligible(character: ScriptCharacter, engine: str) -> list[VoiceProfile]:
    catalog = CATALOGS[engine]
    voices = [voice for voice in catalog if voice.chinese_qa]
    if character.gender in {"男", "女"}:
        voices = [voice for voice in voices if voice.gender == character.gender]
    if engine == "qwen3tts":
        if character.character_type in NON_HUMAN:
            voices = [voice for voice in voices if voice.family == "dialect"]
        elif character.region not in {"", "未知", "中原"}:
            region = [voice for voice in voices if voice.family == "dialect" and any(tag in character.region for tag in voice.regions)]
            if region:
                voices = region + [voice for voice in voices if voice.family == "standard"]
        else:
            voices = [voice for voice in voices if voice.family == "standard"]
    if not voices:
        raise ValueError(f"{engine} 没有满足 {character.name} 性别/类型约束的音色")
    return voices


def _automatic_speed(character: ScriptCharacter) -> float:
    if character.speed != "自动":
        return character.speed_multiplier()
    if character.character_type == "鬼魂":
        return 0.9
    # 不再特意拖慢老人；仅做非常轻微且可覆盖的调整。
    if character.age_group in {"童年", "幼体"}:
        return 1.05
    return 1.0


def assign_cast(
    characters: Iterable[ScriptCharacter],
    chapters: Iterable[ScriptChapter],
    engine: str,
    protagonist_voices: dict[str, str] | None = None,
) -> dict[str, CastAssignment]:
    if engine not in CATALOGS:
        raise ValueError(f"未知 TTS 引擎：{engine}")
    character_list = list(characters)
    graph = adjacency_graph(chapters)
    reserved = {key: value for key, value in (protagonist_voices or {}).items() if value}
    valid = all_voice_ids(engine)
    for gender, voice in reserved.items():
        if voice not in valid:
            raise ValueError(f"{engine} 主角保留音不存在：{gender}={voice}")

    position_order = {"旁白": 0, "主角": 1, "重要角色": 2, "配角": 3, "群体": 4, "未知": 5}
    ordered = sorted(character_list, key=lambda item: (position_order.get(item.position, 9), -len(graph.get(item.name, set())), item.name))
    result: dict[str, CastAssignment] = {}
    for character in ordered:
        override = character.voice_overrides.get(engine)
        if override:
            if override not in valid:
                raise ValueError(f"{character.name} 覆盖的 {engine} 音色不存在：{override}")
            selected = override
            reasons = ["人工覆盖"]
            candidates = [override]
        elif character.position == "主角" and character.gender in reserved:
            selected = reserved[character.gender]
            reasons = [f"{character.gender}主角保留音"]
            candidates = [selected]
        else:
            candidates_scored = sorted(
                ((_candidate_score(character, voice)[0], voice) for voice in _eligible(character, engine)),
                key=lambda pair: (-pair[0], pair[1].voice_id),
            )
            reserved_ids = set(reserved.values())
            candidates_scored = [pair for pair in candidates_scored if pair[1].voice_id not in reserved_ids]
            if not candidates_scored:
                raise ValueError(f"{character.name} 没有可用音色：候选均被主角音保留")
            candidates = [voice.voice_id for _, voice in candidates_scored]
            adjacent_voices = {result[name].voice for name in graph.get(character.name, set()) if name in result}
            selected_profile = next((voice for _, voice in candidates_scored if voice.voice_id not in adjacent_voices), candidates_scored[0][1])
            selected = selected_profile.voice_id
            _, reason = _candidate_score(character, selected_profile)
            reasons = [part for part in reason.split("、") if part] or ["同声别确定性匹配"]
            if selected in adjacent_voices:
                reasons.append("候选耗尽，存在邻接冲突")
        result[character.name] = CastAssignment(selected, _automatic_speed(character), reasons, candidates)
    return result


TYPE_PATTERNS = {
    "机器人": r"机器人|机械人|机甲|仿生人|人工智能|机械守卫",
    "怪兽": r"怪兽|巨兽|魔兽|异兽",
    "妖怪": r"妖怪|妖精|妖魔|狐妖|蛇妖",
    "灵兽": r"灵兽|仙兽|神兽|坐骑",
    "鬼魂": r"鬼魂|幽灵|亡魂|厉鬼",
    "神明": r"神明|天神|神祇|神灵",
}
REGION_PATTERNS = {
    "上海": r"上海|沪上",
    "北京": r"北京|京城人|燕京",
    "南京/江淮": r"南京|江淮",
    "陕西/西北山区": r"陕西|关中|西北山区",
    "闽南/福建/台湾": r"闽南|福建|台湾",
    "天津": r"天津",
    "四川/重庆/西南山区": r"四川|重庆|巴蜀|西南山区",
    "广东/香港/岭南": r"广东|香港|岭南|粤地",
    "海外·英语区": r"英国|美国|加拿大|澳洲|英语区",
    "海外·西班牙/拉美": r"西班牙|拉美|墨西哥|阿根廷",
    "山区": r"山民|山里人|山区长大|来自山里",
}


def enrich_character(character: ScriptCharacter, full_text: str) -> ScriptCharacter:
    """从角色名附近的长期身份线索补充类型和地域，不使用旅行地点。"""
    contexts: list[str] = []
    for match in re.finditer(re.escape(character.name), full_text):
        contexts.append(full_text[max(0, match.start() - 45):match.end() + 45])
    context = "\n".join(contexts)
    kind = character.character_type
    if kind == "人类":
        for candidate, pattern in TYPE_PATTERNS.items():
            if re.search(pattern, context):
                kind = candidate
                break
    region = character.region
    identity_context = "\n".join(
        sentence for sentence in contexts
        if re.search(r"来自|出生|祖籍|故乡|家乡|本地人|土生土长|族人|山民", sentence)
    )
    if region in {"", "未知"}:
        for candidate, pattern in REGION_PATTERNS.items():
            if re.search(pattern, identity_context):
                region = candidate
                break
    return replace(character, character_type=kind, region=region or "未知")
