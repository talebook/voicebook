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

SPEECH_VERBS = "说|道|笑|喊|叫|骂|问|答|哭|嚷|吼|呵斥|嘀咕|低语|感叹|叹|回|应|想|思忖|寻思|喃喃|自语|念"
# 拟声词引文（“咣当！”）不是对白
SFX_WORDS = "咣当|哗啦|轰隆|咔嚓|卡察|扑通|噗通|叮当|哐当|吱呀|呼啦|咕噜|沙沙|轰|砰|嗖|啪|咚|嘭|哗"
SFX_RE = re.compile(rf"^(?:{SFX_WORDS})+[！？。…—\s]*$")
NAME = r"[一-龥]{2,3}"
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
}


def plausible_name(cand: str) -> bool:
    return (cand not in NAME_STOPWORDS
            and not cand.endswith(("地", "得", "的", "着", "了"))
            and not any(w in cand for w in "这那什怎他她它谁"))

R2_BEFORE = re.compile(rf"({NAME})[^“”]{{0,12}}?(?:{SPEECH_VERBS})[^“”]{{0,4}}[:：]?\s*$")
SUBJ_LEAD = re.compile(rf"^({NAME})")


@dataclass
class Quote:
    text: str            # 引文内容（不含引号）
    para_idx: int        # 所在段索引
    span: tuple          # 段内 (start, end)
    speaker: Optional[str] = None
    method: str = ""     # R1/R2/CSI/R3/R4/sfx/unknown
    kind: str = "dialogue"   # dialogue | sfx（拟声词，按旁白处理）


@dataclass
class Attributor:
    csi_model_dir: Optional[Path] = None   # 不传则只用规则层
    names: set = field(default_factory=set)
    _csi: object = None

    # ---------- 人名清单 ----------
    def build_names(self, text: str):
        verb_counts, counts = {}, {}
        for n_len in (2, 3):
            for m in re.finditer(rf"(?=([一-龥]{{{n_len}}})(?:{SPEECH_VERBS}))", text):
                n = m.group(1)
                verb_counts[n] = verb_counts.get(n, 0) + 1
                counts[n] = counts.get(n, 0) + 1
            for para in text.splitlines():
                m = re.match(rf"([一-龥]{{{n_len}}})", para.strip())
                if m:
                    counts[m.group(1)] = counts.get(m.group(1), 0) + 1
        # 必须至少出现一次"名字+说话动词"（仅段首高频不算，避免"剧烈的摇晃"这类误收）
        cand = {n for n, c in counts.items()
                if c >= 2 and verb_counts.get(n, 0) >= 1 and plausible_name(n)}
        # 去掉被更长名字包含的碎片（"长湖"⊂"李长湖"，前后缀都算）
        self.names |= {n for n in cand
                       if not any(o != n and n in o and counts[o] >= counts[n] for o in cand)}

    def to_name(self, cand: str) -> Optional[str]:
        """候选串映射到已知角色名（互为子串即认为同一角色，如"长湖"→"李长湖"）。"""
        for n in sorted(self.names, key=len, reverse=True):
            if cand in n or n in cand:
                return n
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
        # 未知但像人名（2-4字纯汉字）且高置信 → 接受为新角色
        if score >= self.CSI_NEW_NAME and re.fullmatch(r"[一-龥]{2,4}", span) and plausible_name(span):
            self.names.add(span)
            return span
        return None

    @staticmethod
    def is_addressee(name: str, quote_text: str) -> bool:
        """引文中以称呼语出现的名字是受话人，不是说话人（如“项平哥”→李项平被排除）。"""
        tail = name[-2:]
        return bool(re.search(rf"{re.escape(tail)}[哥妹姐弟叔婶兄]", quote_text))

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
        return None, ""

    def rule_fallback(self, paras: List[str], q: Quote, recent: List[str]):
        para = paras[q.para_idx]
        # R3: 引文独立成段 → 邻段旁白主语（排除被称呼者）
        if not para[:q.span[0]].strip() and not para[q.span[1]:].strip():
            for j in (q.para_idx + 1, q.para_idx - 1):
                if 0 <= j < len(paras) and not QUOTE_RE.search(paras[j]):
                    m = SUBJ_LEAD.match(paras[j])
                    name = self.to_name(m.group(1)) if m else None
                    if name and not self.is_addressee(name, q.text):
                        return name, "R3"
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
            state = torch.load(d / "csi-v1.pth", map_location="cpu", weights_only=True)
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

        recent: List[str] = []
        for qi, q in enumerate(quotes):
            # 拟声词不是对白
            if SFX_RE.match(q.text):
                q.kind, q.method = "sfx", "sfx"
                continue
            # L1 高置信
            speaker, method = self.rule_attribute(paras, q)
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
            if speaker:
                recent.append(speaker)
        return quotes
