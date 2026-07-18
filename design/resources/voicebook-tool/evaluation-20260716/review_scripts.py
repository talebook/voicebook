#!/usr/bin/env python3
"""对 inspect 结果做可审计的人工校正，再用于试听生成。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from book2audio.script import parse_voicebook_script, write_voicebook_script


ROOT = Path(__file__).resolve().parent
REVIEWS = {
    "xiyouji": {
        "aliases": {"石猴": "孫悟空"},
        "updates": {
            "孫悟空": {"position": "主角", "character_type": "灵兽", "gender": "男", "age_group": "成年", "region": "花果山", "voice_description": "靈動、果敢", "speed": "x1.05"},
            "眾猴": {"position": "群体", "character_type": "灵兽", "gender": "中性", "age_group": "成年", "region": "花果山", "voice_description": "活潑"},
            "猿猴": {"character_type": "灵兽", "gender": "男", "age_group": "成年", "region": "花果山"},
            "小妖": {"character_type": "妖怪", "gender": "男", "age_group": "成年", "voice_description": "機靈"},
            "魔王": {"character_type": "怪兽", "gender": "男", "age_group": "成年", "voice_description": "粗啞、威嚴", "speed": "x0.95"},
            "祖師": {"character_type": "神明", "gender": "男", "age_group": "古老", "voice_description": "沉穩、威嚴", "speed": "x0.95"},
            "仙童": {"gender": "男", "age_group": "少年"},
            "樵夫": {"gender": "男", "age_group": "青年", "region": "山區"},
        },
    },
    "rulinwaishi": {
        "aliases": {},
        "updates": {
            "王冕": {"position": "主角", "gender": "男", "age_group": "青年", "voice_description": "清朗、克制"},
            "周進": {"position": "重要角色", "gender": "男", "age_group": "老年", "voice_description": "蒼老、拘謹", "speed": "x1.0"},
            "秦老": {"gender": "男", "age_group": "老年"},
            "翟買辦": {"gender": "男", "age_group": "中年"},
        },
    },
    "hongloumeng": {
        "aliases": {"聽道人": "道人"},
        "updates": {
            "賈雨村": {"position": "主角", "gender": "男", "age_group": "青年", "voice_description": "清晰、世故"},
            "冷子興": {"position": "重要角色", "gender": "男", "age_group": "中年"},
            "甄士隱": {"gender": "男", "age_group": "中年", "voice_description": "溫和"},
            "甄家娘子": {"gender": "女", "age_group": "中年", "voice_description": "柔和"},
            "道人": {"position": "重要角色", "gender": "男", "age_group": "老年", "voice_description": "飄逸、沉穩"},
        },
    },
}


def review(book_id: str, config: dict) -> None:
    path = ROOT / book_id / "book.script"
    script = parse_voicebook_script(path)
    aliases = config["aliases"]
    for chapter in script.chapters:
        for segment in chapter.segments:
            base, separator, state = segment.tag.partition("@")
            base = aliases.get(base, base)
            segment.tag = base + (separator + state if separator else "")

    by_name = script.character_map()
    for old, new in aliases.items():
        if new not in by_name and old in by_name:
            by_name[new] = replace(by_name[old], name=new)
    for name, values in config["updates"].items():
        if name not in by_name:
            print(f"跳过未在本次脚本出场的角色：{book_id}/{name}")
            continue
        by_name[name] = replace(by_name[name], **values)

    used = {
        segment.character for chapter in script.chapters for segment in chapter.segments
        if segment.character not in {"旁白", "?", "音"}
    }
    ordered_names = [character.name for character in script.characters if character.name not in aliases]
    script.characters = [
        by_name[name] for name in ordered_names
        if name == "旁白" or name in used
    ]
    # 别名目标原先不存在时，紧跟旁白插入，保证角色表可读。
    for target in aliases.values():
        if target in used and all(character.name != target for character in script.characters):
            script.characters.append(by_name[target])
    script.extra_meta["人工审查"] = "已校正明显别名、主角定位、性别、年龄与非人类类型；[?] 保持安全降级"
    write_voicebook_script(script, path)
    parse_voicebook_script(path)
    print(f"已审查：{path}")


def main() -> None:
    for book_id, config in REVIEWS.items():
        review(book_id, config)


if __name__ == "__main__":
    main()
