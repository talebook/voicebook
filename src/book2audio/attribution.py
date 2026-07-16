"""说话人识别：L1 规则层 + L2 CSI 模型（chinese-roberta-wwm-ext-large-csi）融合

分层策略：
  L1 规则（高置信）: R1 引号后随名字+动词 / R2 引号前导名字+动词 → 直接采纳
  L2 CSI 模型      : 抽取式MRC从上下文抽说话人span，span映射到角色名才采纳
  L1 规则（低置信）: R3 邻段旁白主语 / R4 双人轮替 → L2 给不出人名时兜底
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SPEECH_VERBS = ("说|道|笑|喊|叫|骂|问|答|哭|嚷|吼|呵斥|嘀咕|低语|感叹|叹|回|应|想|思忖|寻思|喃喃|自语|念"
                "|說|問|罵|嘆|應|喚|講")  # 繁体变体（繁体书源）
# 拟声词引文（“咣当！”）不是对白
SFX_WORDS = "咣当|哗啦|轰隆|咔嚓|卡察|扑通|噗通|叮当|哐当|吱呀|呼啦|咕噜|沙沙|轰|砰|嗖|啪|咚|嘭|哗"
SFX_RE = re.compile(rf"^(?:{SFX_WORDS})+[！？。…—\s]*$")
# 人名：中文候选容纳“姓名+动作”，随后由 clean_name_candidate 剥离动作。
NAME = r"(?:[一-龥]{1,4}·)+[一-龥]{1,4}|[一-龥]{2,6}"
DOTTED_RE = re.compile(r"(?:[一-龥]{1,4}·)+[一-龥]{1,4}")
QUOTE_RE = re.compile(r"[“「]([^”」]*)[”」]")
SENT_SPLIT = re.compile(r"(?<=[。！？\n])")
# CSI span 清洗：剥掉亲属/排行称谓前缀与语气成分
TITLE_PREFIX = re.compile(r"^(大哥|二哥|三哥|四哥|大姐|二姐|三弟|四弟|老大|老二|老三|老四)")
PRONOUNS = {"他", "她", "它", "他们", "她们", "女孩", "男孩", "女子", "男子", "老者", "少年", "众人"}
# "副词+说话动词"高频搭配会被词频法误收为人名（"连忙道"/"默默地想"）
NAME_STOPWORDS = {
    "这么", "那么", "什么", "怎么", "连忙", "急忙", "赶忙", "顿时", "默默", "突然", "忽然",
    "马上", "立刻", "随即", "当即", "只是", "可是", "但是", "于是", "然后", "这样", "那样",
    "如此", "一边", "一面", "接着", "跟着", "继续", "开口", "闻言", "当下", "心中", "心里",
    "口中", "大声", "小声", "低声", "高声", "连声", "齐声", "失声", "出声", "轻声", "沉声",
    "厉声", "柔声", "朗声", "一声", "说完", "听完", "点头", "摇头", "笑着", "哭着", "似乎",
    "仿佛", "彷佛", "不禁", "不由", "暗暗", "暗自", "喃喃", "自己", "众人", "有人", "no",
    "不知", "谁知", "哪知", "岂知", "只见", "只听", "便是", "就是", "正是", "于此",
    # 泛称（指人但非具体角色名，会造成幽灵角色/错配音色）
    "老人", "老者", "老汉", "老妪", "老翁", "老头", "老头儿", "道童", "童子", "妇人",
    "汉子", "青年", "丫鬟",
    # 古典/繁体文本中的过渡语、动作和泛指词
    "這一", "這個", "那個", "何曾", "彼此", "今日", "此時", "方纔", "方才",
    "雖然", "雖然如此", "且聽", "且聽下", "下一", "上一", "內中一人", "二人",
    "大眾", "眾人", "出來", "入世", "意欲", "自不必", "方纔所", "田庄", "口氣",
    "口訣", "歡喜", "滿心歡喜", "靜坐", "金光", "金蓮", "汪洋", "蒼梧", "順澗",
    "開口", "陪笑", "笑問", "因笑", "僧笑", "僧便", "道人笑", "看了一", "了一",
    "來說", "聽見", "聲叫", "聲高叫", "些甚麼", "修些甚麼", "甚麼", "什麼",
    "乃說", "口內", "唐突", "拍掌", "正存", "金陵", "黃庭", "叩頭", "聽下",
    "說說", "空空", "纔所", "二仙", "石碣", "金丸珠彈", "甄府", "賈府", "賈氏",
}

SPEAKER_ACTION_SUFFIX_RE = re.compile(
    r"(?:低聲|高聲|大聲|小聲|輕聲|沉聲|厲聲|應聲|連聲|失聲|近前|回頭|聞言|"
    r"心裡想|心里想|笑著|哭著|忙陪|陪笑|忙笑|又笑|因笑|遂笑|便笑|乃笑|拍案|施禮|"
    r"拍手稱揚|拍手称扬|向窗外看|遂向石頭|遂向石头|在傍|在旁|裡想|里想|歎|嘆|冷|陪|"
    r"聽|聞|笑|喝|問|答|叫|喊|罵|說|说|道|"
    r"因|又|忙|便|遂|乃|即|先)+$"
)
SPEAKER_NOISE_PREFIX_RE = re.compile(r"^(?:只聽|只听|忽聽|忽听|卻聽|却听|但聽|但听|聽(?=道人)|听(?=道人)|向著|向着|向)")


def clean_name_candidate(candidate: str) -> str:
    """把“雨村忙笑/悟空應聲/祖師又笑”收敛回角色本名。"""
    value = candidate.strip("，。！？：；、 ")
    previous = None
    while value != previous and len(value) >= 2:
        previous = value
        value = SPEAKER_ACTION_SUFFIX_RE.sub("", value)
        value = SPEAKER_NOISE_PREFIX_RE.sub("", value)
    return value


def plausible_name(cand: str) -> bool:
    cand = clean_name_candidate(cand)
    return (2 <= len(cand) <= 12
            and cand not in NAME_STOPWORDS
            and not cand.endswith(("地", "得", "的", "着", "了", "家"))   # "袁家"是家族非个人
            and not cand.startswith(("不", "没", "沒", "无", "無", "别", "別", "莫", "并", "並",
                                     "很", "太", "更", "越", "要", "如", "若", "就", "才", "倒",
                                     "且聽", "只聽", "雖然", "方纔", "方才", "了一", "個", "出門",
                                     "即開", "厲聲", "應聲", "心歡", "滿心", "是個", "字門", "非仙",
                                     "天產", "面有", "行主人", "哈哈", "向眾"))
            and not cand.endswith(("開口", "歡喜", "嘻嘻", "拍案", "施禮", "人氏", "府", "家集"))
            and "名" not in cand
            and not any(w in cand for w in "这這那什怎他她它谁誰么麼"))


# 常见姓氏：用于过滤 jieba-NER 通道的噪声（"小河/修仙"等误判）
SURNAMES = ("李王张刘陈杨黄赵周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜"
            "叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦傅方白邹孟熊秦邱江尹薛闫段雷侯龙史陶"
            "黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤欧阳司马诸葛")
SURNAMES += "張劉陳楊黃趙吳孫馬羅鄭謝馮鄧曾肖董袁蔣蔡餘葉蘇魏呂盧薑崔鐘譚陸汪範廖賈韋傅鄒龔邵萬錢嚴覃戴湯歐陽諸葛賈甄孫吳"

R2_BEFORE = re.compile(rf"({NAME})[^“”]{{0,12}}?(?:{SPEECH_VERBS})[^“”]{{0,4}}[:：]?\s*$")
SUBJ_LEAD = re.compile(rf"^({NAME})")
# 呼唤句："项平哥！" / "阿爹！" / "对了，爹。"（可带短前导语气词）
VOCATIVE_RE = re.compile(r"^[一-龥]{0,3}[，、]?\s*阿?[一-龥]{0,3}[哥姐妹弟叔婶爷奶爹娘伯][！？。…—]*$")


# 情绪/状态线索：邻近旁白的"虚弱地说/怒喝/低声道"等 → 该句对白的发声状态
STATE_CUES = {
    "虚弱": "虚弱|无力|气若游丝|有气无力|奄奄|喘息|颤声|颤抖|挣扎着|气喘",
    "愤怒": "怒|愤|厉声|咆哮|呵斥|怒喝|怒吼|喝道|咬牙|暴喝",
    "冷淡": "冷冷|冷淡|淡淡|淡然|漠然|冷然|冷声|嗤笑|不屑",
    "低语": "低声|低语|喃喃|小声|轻声|耳语|呢喃|附耳",
    "悲伤": "悲|哽咽|啜泣|含泪|凄然|哭着|泣|颤抖着哭",
    "急切": "急忙|连忙|急道|忙道|焦急|慌忙|急切|忙不迭|惊呼",
}


@dataclass
class Quote:
    text: str            # 引文内容（不含引号）
    para_idx: int        # 所在段索引
    span: tuple          # 段内 (start, end)
    speaker: Optional[str] = None
    method: str = ""     # R1/R2/CSI/R3/R4/sfx/unknown
    kind: str = "dialogue"   # dialogue | sfx（拟声词，按旁白处理）
    state: Optional[str] = None  # 虚弱/愤怒/冷淡/低语/悲伤/急切（None=平稳）


@dataclass
class Attributor:
    csi_model_dir: Optional[Path] = None   # 不传则只用规则层
    names: set = field(default_factory=set)
    _csi: object = None

    # ---------- 人名清单 ----------
    def build_names(self, text: str):
        """双通道：①名字+说话动词共现（高精度） ②jieba-NER（高召回，姓氏过滤）"""
        verb_counts, counts = {}, {}
        # 通道3: 带·的译名（jieba 切不动，正则直取），出现≥2次
        for m in DOTTED_RE.finditer(text):
            n = m.group()
            counts[n] = counts.get(n, 0) + 1
        for n in [n for n, c in counts.items() if c >= 2]:
            verb_counts[n] = 1
        counts = {n: c for n, c in counts.items() if c >= 2}
        # 通道2: jieba 词性标注 nr/nrt（nrt=音译名）
        import jieba.posseg as pseg
        ner_counts: dict = {}
        ner_flags: dict = {}
        for w, flag in pseg.cut(text):
            w = clean_name_candidate(w)
            if flag in ("nr", "nrt") and 2 <= len(w) <= 4:
                ner_counts[w] = ner_counts.get(w, 0) + 1
                ner_flags[w] = flag
        for n, c in ner_counts.items():
            # 中文名要求百家姓打头；音译名(nrt)和4字nr（奥雷连诺）不受姓氏约束
            surname_ok = n[0] in SURNAMES or ner_flags[n] == "nrt" or len(n) == 4
            if c >= 2 and surname_ok and plausible_name(n):
                # 截断修复：若原文中该候选≥80%场合后面跟同一个字，则补全（"李尺"→"李尺泾"）
                while len(n) < 4:
                    nxt = [m for m in re.findall(rf"{re.escape(n)}([一-龥])", text)]
                    if nxt and nxt.count(max(set(nxt), key=nxt.count)) >= 0.8 * len(re.findall(re.escape(n), text)):
                        ext = max(set(nxt), key=nxt.count)
                        if ext in "的地得了着说道哥妹姐弟":  # 跟的是功能字/称谓则停止
                            break
                        n = n + ext
                    else:
                        break
                counts[n] = counts.get(n, 0) + c
                verb_counts[n] = verb_counts.get(n, 0) + 1  # NER 身份即证据
        for n_len in range(2, 7):
            for m in re.finditer(
                rf"(?=([一-龥]{{{n_len}}})(?:{SPEECH_VERBS})\s*[:：]?\s*[“「])",
                text,
            ):
                n = clean_name_candidate(m.group(1))
                if not plausible_name(n):
                    continue
                verb_counts[n] = verb_counts.get(n, 0) + 1
                counts[n] = counts.get(n, 0) + 1
            for para in text.splitlines():
                m = re.match(rf"([一-龥]{{{n_len}}})", para.strip())
                if m:
                    counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        # 必须至少出现一次"名字+说话动词"（仅段首高频不算，避免"剧烈的摇晃"这类误收）
        cand = {n for n, c in counts.items()
                if c >= 2 and verb_counts.get(n, 0) >= 1 and plausible_name(n)}

        # 去掉碎片候选："长湖"⊂"李长湖"；"李渊"⊂{李渊平,李渊蛟}（在原文中几乎不独立出现）
        def fragment(n):
            # 词性分词反复独立识别出的常见姓氏人名优先保留；避免“王冕屈”等
            # 偶发错误长词反过来吞掉全文高频真名“王冕”。
            if n[0] in SURNAMES and ner_counts.get(n, 0) >= 3:
                return False
            longers = [o for o in cand if o != n and n in o]
            if longers and any(counts[o] >= counts[n] for o in longers):
                return True
            if longers:
                total = len(re.findall(re.escape(n), text))
                inside = sum(len(re.findall(re.escape(o), text)) for o in longers)
                if total - inside <= 1:
                    return True
            # "李渊"⊂{李渊平,李渊蛟}：≥2个不同延伸字各出现≥2次 → 多名字公共前缀，丢弃
            ext = re.findall(rf"{re.escape(n)}([一-龥])", text)
            frequent_ext = {c for c in set(ext) if ext.count(c) >= 2}
            return len(frequent_ext) >= 2 and len(ext) >= 0.9 * len(re.findall(re.escape(n), text))
        names = {n for n in cand if not fragment(n)}
        # 别名归并：·译名的分量（"布恩迪亚"⊂"霍·阿·布恩迪亚"）不作为独立角色
        dotted = {n for n in names if "·" in n}
        names -= {n for n in names if "·" not in n
                  and any(n in d.replace("·", "") or any(n in p or p in n for p in d.split("·") if len(p) >= 2)
                          for d in dotted)}
        self.names |= names

        # 单人戏兜底：全文没有任何专名角色（如《老人与海》的"老人"），接纳主导泛称
        if not self.names:
            generics = [("老人", "老者", "老頭", "老汉", "男孩", "女孩", "少年", "少女", "孩子")]
            hits = {g: len(re.findall(g, text)) for g in generics[0]}
            top = max(hits, key=hits.get)
            if hits[top] >= 5:
                self.names.add(top)

    def to_name(self, cand: str) -> Optional[str]:
        """候选串映射到已知角色名（规范化别名）：
        子串："长湖"→"李长湖"；译名分量："阿卡蒂奥"→"霍·阿卡蒂奥"；
        昵称："云儿"/"小云"/"阿云"→"孟灼云"（要求全表唯一命中）。"""
        cand = clean_name_candidate(cand.strip("·"))
        if not cand:
            return None
        if cand in self.names:
            return cand
        for n in sorted(self.names, key=len, reverse=True):
            if cand in n or n in cand:
                return n
            if "·" in n and any(len(p) >= 2 and (cand in p or p in cand) for p in n.split("·")):
                return n
        # 昵称模式：阿X/小X/X儿（核心字需在某个角色名中且唯一）
        m = re.fullmatch(r"[阿小]([一-龥]{1,3})", cand) or re.fullmatch(r"([一-龥]{1,2})儿", cand)
        if m and m.group(1) not in "人孩子头哥姐":
            hits = [n for n in self.names if m.group(1) in n]
            if len(hits) == 1:
                return hits[0]
        return None

    # CSI 置信度阈值：低于 ACCEPT 整体不采纳；新角色名要求更高的 NEW_NAME
    CSI_ACCEPT = 8.5
    CSI_NEW_NAME = 9.5

    def clean_span(self, span: str, score: float) -> Optional[str]:
        """清洗 CSI 输出 span → 规范角色名；代词/泛称/低置信返回 None。"""
        if score < self.CSI_ACCEPT:
            return None
        span = TITLE_PREFIX.sub("", span.strip("，。！？：；、 \n"))
        if not span or span in PRONOUNS:
            return None
        known = self.to_name(span)
        if known:
            return known
        # 未知但像人名（2-4字纯汉字或·译名）且高置信 → 接受为新角色
        if score >= self.CSI_NEW_NAME and re.fullmatch(NAME, span) and plausible_name(span):
            self.names.add(span)
            return span
        return None

    @staticmethod
    def detect_state(paras, q) -> Optional[str]:
        """从引文邻近旁白（同段引号前后 + 独立成段时的上一段尾）识别发声状态。"""
        para = paras[q.para_idx]
        ctx = para[max(0, q.span[0] - 14):q.span[0]] + para[q.span[1]:q.span[1] + 14]
        if not para[:q.span[0]].strip() and not para[q.span[1]:].strip() and q.para_idx > 0:
            ctx += paras[q.para_idx - 1][-16:]
        for state, cues in STATE_CUES.items():
            if re.search(cues, ctx):
                return state
        return None

    @staticmethod
    def is_addressee(name: str, quote_text: str) -> bool:
        """引文中以称呼语出现的名字是受话人，不是说话人（如“项平哥”→李项平、“云儿”→孟灼云）。"""
        tail = name[-2:]
        if re.search(rf"{re.escape(tail)}[哥妹姐弟叔婶兄]", quote_text):
            return True
        # 昵称式呼唤："云儿。" → 排除名字含"云"的角色
        m = re.fullmatch(r"([一-龥]{1,2})儿[！？。，…—\s]*", quote_text.strip())
        return bool(m and m.group(1) in name)

    # ---------- L1 规则 ----------
    def rule_attribute(self, paras: List[str], q: Quote):
        para = paras[q.para_idx]
        before, after = para[:q.span[0]], para[q.span[1]:]
        # R1: 引号后紧跟 名字+动词
        m = re.match(rf"\s*({NAME})[^“”]{{0,8}}?(?:{SPEECH_VERBS})", after)
        if m and self.to_name(m.group(1)):
            return self.to_name(m.group(1)), "R1"
        # R2: 引号前 名字+动词
        m = R2_BEFORE.search(before)
        if m and self.to_name(m.group(1)):
            return self.to_name(m.group(1)), "R2"
        # R5: 引文独立成段且上一段以冒号收尾（"X喊道："↵ 引文）
        # 取离冒号最近（最右）的角色名："李曦峸点头退下，李渊平仔细算了算：" → 李渊平
        if not before.strip() and not after.strip() and q.para_idx > 0:
            prev = paras[q.para_idx - 1]
            if prev.rstrip().endswith(("：", ":")):
                # 只在冒号所在的最后分句找名字，避免把前面分句的宾语当说话人
                # （"…交到李曦峸手中，继续道："→ 最后分句"继续道"无名字，不触发）
                last_clause = re.split(r"[，；]", prev.rstrip("：: "))[-1]
                hits = [(last_clause.rfind(n), n) for n in self.names if n in last_clause]
                if hits:
                    name = max(hits)[1]
                    if not self.is_addressee(name, q.text):
                        return name, "R5"
        return None, ""

    def rule_fallback(self, paras: List[str], q: Quote, recent: List[str]):
        para = paras[q.para_idx]
        # R1b: 引号后紧跟 名字+动作（无说话动词，如"阿爹！"李项平仰着头望着李木田）
        m = re.match(rf"\s*({NAME})", para[q.span[1]:])
        if m:
            name = self.to_name(m.group(1))
            if name and not self.is_addressee(name, q.text):
                return name, "R1b"
        # R3: 引文独立成段 → 邻段旁白主语（排除被称呼者）
        if not para[:q.span[0]].strip() and not para[q.span[1]:].strip():
            for j in (q.para_idx + 1, q.para_idx - 1):
                if 0 <= j < len(paras) and not QUOTE_RE.search(paras[j]):
                    m = SUBJ_LEAD.match(paras[j])
                    name = self.to_name(m.group(1)) if m else None
                    if name and not self.is_addressee(name, q.text):
                        return name, "R3"
        # R6: 呼唤句前瞻——说话人通常在后文现身（"项平哥！"→排除受话人→后文最先出场的角色）
        if VOCATIVE_RE.match(q.text):
            for j in range(q.para_idx + 1, min(len(paras), q.para_idx + 9)):
                hits = [(paras[j].index(n), n) for n in self.names
                        if n in paras[j] and not self.is_addressee(n, q.text)]
                if hits:
                    return min(hits)[1], "R6"
        # R4: 双人轮替（最近窗口内恰好两人对话时，取与上一位不同者）
        two = set(recent[-3:])
        if len(two) == 2:
            other = next(n for n in two if n != recent[-1])
            if not self.is_addressee(other, q.text):
                return other, "R4"
        return None, ""

    # ---------- L2 CSI ----------
    def _load_csi(self):
        if self._csi is None:
            import torch
            from tokenizers import BertWordPieceTokenizer
            from transformers import BertConfig, BertForQuestionAnswering
            d = Path(self.csi_model_dir)
            tok = BertWordPieceTokenizer(str(d / "vocab.txt"), lowercase=True)
            tok.enable_truncation(max_length=512, strategy="only_second")
            model = BertForQuestionAnswering(BertConfig.from_json_file(d / "config.json"))
            # 优先 fp16 存档（体积减半），加载后转回 fp32 计算（CPU 上 fp16 算子反而慢）
            ckpt = d / "csi-v1-fp16.pth" if (d / "csi-v1-fp16.pth").exists() else d / "csi-v1.pth"
            state = torch.load(ckpt, map_location="cpu", weights_only=True)
            state = {k: (v.float() if v.is_floating_point() else v) for k, v in state.items()}
            model.load_state_dict(state, strict=False)
            model.eval()
            self._csi = (tok, model)
        return self._csi

    def csi_attribute(self, units, ui: int, win=3):
        """units: [(text, is_quote)]; ui: 引文单元索引。返回 (span, score)。"""
        import torch
        tok, model = self._load_csi()
        quote = units[ui][0]
        pre = "".join(u[0] for u in units[max(0, ui - win):ui])
        post = "".join(u[0] for u in units[ui + 1:ui + 1 + win])
        if ui > 0 and not units[ui - 1][1]:
            question = units[ui - 1][0] + quote
        elif ui + 1 < len(units) and not units[ui + 1][1]:
            question = quote + units[ui + 1][0]
        else:
            question = quote
        context = f"{pre} {quote} {post}"

        enc = tok.encode(question, context)
        with torch.no_grad():
            out = model(input_ids=torch.tensor([enc.ids]),
                        token_type_ids=torch.tensor([enc.type_ids]),
                        attention_mask=torch.tensor([enc.attention_mask]))
        is_ctx = torch.tensor([sid == 1 for sid in enc.sequence_ids])
        is_ctx &= torch.tensor([i not in (101, 102) for i in enc.ids])
        s_log = out.start_logits[0].masked_fill(~is_ctx, -1e9)
        e_log = out.end_logits[0].masked_fill(~is_ctx, -1e9)
        best, best_score = None, -1e18
        for s in s_log.topk(10).indices.tolist():
            for e in e_log.topk(10).indices.tolist():
                if s <= e <= s + 10:
                    sc = (s_log[s] + e_log[e]).item()
                    if sc > best_score:
                        best, best_score = (s, e), sc
        if best is None:
            return "", best_score
        return context[enc.offsets[best[0]][0]:enc.offsets[best[1]][1]], best_score

    # ---------- 主流程 ----------
    def attribute(self, text: str) -> List[Quote]:
        self.build_names(text)
        paras = [p.strip() for p in text.splitlines() if p.strip()]
        # 句子单元（给CSI用）：旁白按句切，引文整体一个单元
        units, unit_of_quote = [], {}
        quotes: List[Quote] = []
        for pi, para in enumerate(paras):
            pos = 0
            for m in QUOTE_RE.finditer(para):
                for s in SENT_SPLIT.split(para[pos:m.start()]):
                    if s.strip():
                        units.append((s.strip(), False))
                quotes.append(Quote(m.group(1), pi, (m.start(), m.end())))
                unit_of_quote[len(quotes) - 1] = len(units)
                units.append((m.group(0), True))
                pos = m.end()
            for s in SENT_SPLIT.split(para[pos:]):
                if s.strip():
                    units.append((s.strip(), False))

        # R7: 连续说话——上一段是"（他）继续道：/复又道："且段内无角色名 → 延续上一条说话人
        CONT_RE = re.compile(r"(?:继续|复又|接着|又|续)(?:说|道)[：:]\s*$")

        recent: List[str] = []
        for qi, q in enumerate(quotes):
            # 拟声词不是对白
            if SFX_RE.match(q.text):
                q.kind, q.method = "sfx", "sfx"
                continue
            # L1 高置信
            speaker, method = self.rule_attribute(paras, q)
            if not speaker and recent and q.para_idx > 0:
                prev = paras[q.para_idx - 1]
                last_clause = re.split(r"[，；]", prev.rstrip())[-1]
                if CONT_RE.search(prev) and not any(n in last_clause for n in self.names):
                    speaker, method = recent[-1], "R7"
            # L2 CSI
            if not speaker and self.csi_model_dir:
                span, score = self.csi_attribute(units, unit_of_quote[qi])
                name = self.clean_span(span, score)
                if name and not self.is_addressee(name, q.text):
                    speaker, method = name, "CSI"
            # L1 低置信兜底
            if not speaker:
                speaker, method = self.rule_fallback(paras, q, recent)
            q.speaker, q.method = speaker, method or "unknown"
            q.state = self.detect_state(paras, q)
            if speaker:
                recent.append(speaker)

        # 第二遍：CSI 动态发现的新角色（如对白中才现身的人物）可能改善低置信归属
        for qi, q in enumerate(quotes):
            if q.kind == "sfx" or q.method not in ("R6", "R4", "unknown"):
                continue
            recent2 = [x.speaker for x in quotes[:qi] if x.speaker]
            speaker, method = self.rule_fallback(paras, q, recent2)
            if speaker:
                q.speaker, q.method = speaker, method

        # R8 单人场景：全文唯一角色时，未归属对白都是他的（独角戏/内心独白）
        if len(self.names) == 1:
            only = next(iter(self.names))
            for q in quotes:
                if q.kind == "dialogue" and not q.speaker:
                    q.speaker, q.method = only, "R8"
        return quotes
