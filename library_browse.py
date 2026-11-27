"""本人作品浏览索引。catalog(lib) 须在调用方已有的 lib.locked() 内执行。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

__all__ = ["catalog", "readable_blocks"]

_SCHEMA = 2
_DOMAINS = {
    "ai": "AI与知识管理",
    "media": "传播与人性",
    "architecture": "建筑与人文",
    "business": "商业与经营",
}
# 只作为缺少有效映射时的领域证据，不用固定词表生成话题。
_DOMAIN_TERMS = {
    "ai": ("AI", "人工智能", "知识管理", "知识库", "大语言模型", "大模型", "提示词"),
    "media": ("传播", "人性", "媒介", "新媒体", "社交媒体", "受众", "舆论"),
    "architecture": ("建筑", "人文", "城市设计", "城市规划", "空间设计", "城乡规划"),
    "business": ("商业", "经营", "企业管理", "创业", "盈利", "供应链", "营销"),
}
_ARCHIVE = re.compile(
    r"^VID[-_ ]+ARCHIVE(?:[-_ ]+\d+)+[\s_—–:：|/.-]*", re.I
)
_EMPTY_TITLE = re.compile(
    r"(?:getnote(?:[\s_:#：.-]*(?:笔记|记录|编号))?[\s_:#：.-]*[\d_-]*"
    r"|未命名(?:标题|笔记|文档|作品)?(?:[\s_()（）-]*\d+[)）]?)?"
    r"|untitled(?:\s*\d+)?)", re.I
)
_META = re.compile(
    r"^(?:(?:正文来源|材料来源|原文来源|来源(?:说明)?|校订说明|校对说明|转录说明)"
    r"(?:\s*[:：].*)?|原始\s*ASR\s*(?:已)?校订为.*)$", re.I
)
_QUOTE_PUNCT = re.compile(r"[\s,，。.!！？?、;；：:…]+")
_LOCAL_ERRORS = (FileNotFoundError, NotADirectoryError, PermissionError, IsADirectoryError)


def _load(path):
    with open(path, encoding="utf-8-sig") as stream:
        return json.load(stream)


def _atomic(path, obj):
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".browse-",
            suffix=".tmp", delete=False
        ) as stream:
            name = stream.name
            json.dump(obj, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def _plain(value):
    """清理标题的外层 Markdown，不用于改写正文。"""
    text = "" if value is None else str(value).strip().lstrip("\ufeff").strip()
    text = re.sub(r"^#{1,6}[ \t]+", "", text)
    text = re.sub(r"[ \t]+#{1,6}$", "", text).strip()
    for marker in ("**", "__", "`"):
        if text.startswith(marker) and text.endswith(marker) and len(text) > 2 * len(marker):
            text = text[len(marker):-len(marker)].strip()
            break
    return text


def _clean_title(value):
    text = _plain(value)
    while text:
        previous = text
        text = re.sub(
            r"^【(?:平台版校订|平台版终稿|校订版|校订逐字稿)】[ \t]*",
            "",
            text,
        )
        text = re.sub(
            r"^VID-ARCHIVE-\d{8}-\d+_(?:\d+_(?=\S))?(?=\S)",
            "",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"[_＿][ \t]*(?:校订逐字稿|终稿逐字稿|机器逐字稿"
            r"(?:[（(][ \t]*raw[ \t]+ASR[ \t]*待校订[ \t]*[）)])?)$",
            "",
            text,
            flags=re.I,
        )
        suffix = re.search(
            r"[ \t\u3000_＿|｜]*(?:定时原始ASR映射|原始ASR映射|公众号平台原文)$",
            text,
            flags=re.I,
        )
        if suffix and text[:suffix.start()].strip():
            text = text[:suffix.start()]
        text = _plain(text)
        if text == previous:
            break
    return text


_RV_NUMBER = re.compile(
    r"^(?:[一二三四五六七八九十百]+[、.．]|"
    r"\d+[、.．](?!\d)|[（(][一二三四五六七八九十百\d]+[）)])[ \t]*"
)
_RV_HANDWRITTEN = re.compile(
    r"^(?:IMG[_＿](?:原段|原始L\d+)|原始L\d+)"
    r"(?:[ \t]*[～~—–至-][ \t]*(?:原始)?L?\d+)?$",
    re.I,
)
_RV_HEADINGS = {
    "终稿正文(保留原分段)": "final_segmented",
    "终稿正文(保留原段落)": "final_segmented",
    "终稿正文(连续)": "final_continuous",
    "终稿正文": "edited",
    "校订正文": "edited",
    "校订逐字稿": "edited",
    "主文本": "main",
    "原始asr全文": "raw_full",
    "原始asr": "raw",
    "rawasr": "raw",
    "原始逐字稿": "raw",
    "原始逐字稿(未删改,供比对)": "raw_comparison",
    "时间戳分段(原始asr)": "raw_timed",
    "时间戳分段(rawasr)": "raw_timed",
    "机器逐字稿": "raw",
    "机器逐字稿(rawasr待校订)": "raw",
    "rawasr待校订": "raw",
    "校订明细": "corrections",
    "连续正文": "edited", "带时间戳分段": "raw_timed",
    "校订稿真源": "metadata",
    "校对表": "corrections",
    "合规标注": "metadata",
    "平台信息": "metadata",
    "事实与引用边界": "citation_metadata",
}
_RV_FORMAL = frozenset(("final_segmented", "final_continuous", "edited"))
_RV_RAW = frozenset(("raw", "raw_full", "raw_timed", "raw_comparison"))
_RV_NEWLINE = re.compile(r"(\r\n|\r|\n)")
_RV_ASR_TABLE = re.compile(
    r"(?im)^[ \t]*\|[ \t]*原始[ \t]*ASR[ \t]*\|[ \t]*校订为[ \t]*\|"
)
_RV_CLOCK = r"(?:\d{1,3}[:：])?[0-5]?\d[:：][0-5]\d(?:[.,，．]\d{1,3})?"
_RV_RANGE = (
    rf"{_RV_CLOCK}(?:[ \t]*(?:-->|→|[-–—~～]|至)[ \t]*{_RV_CLOCK})?"
)
_RV_SPEAKER = (
    r"(?:(?:说话人|讲话人|发言人|讲者|speaker|spk)"
    r"[ \t]*(?:[_#-][ \t]*)?(?:\d+|[A-Za-z]|[甲乙丙丁])"
    r"|未知说话人|未知发言人)"
)
_RV_MARKER = re.compile(
    rf"^[ \t]*(?:"
    rf"\[[ \t]*(?:{_RV_RANGE}|{_RV_SPEAKER})[ \t]*\]"
    rf"|【[ \t]*(?:{_RV_RANGE}|{_RV_SPEAKER})[ \t]*】"
    rf"|[（(][ \t]*(?:{_RV_RANGE}|{_RV_SPEAKER})[ \t]*[）)]"
    rf"|{_RV_SPEAKER}(?=[ \t]*(?:[:：]|$))"
    rf"|{_RV_SPEAKER}(?=[ \t]+(?:{_RV_CLOCK}(?!\d)|[\[【（(]))"
    rf"|{_RV_RANGE}(?![\d:：.,，．])(?=[ \t]|[|｜\[\(【（]|$)"
    rf")[ \t]*(?:[:：|｜][ \t]*)?",
    re.I,
)


def _rv_heading_key(value):
    text = _plain(value)
    text = _RV_NUMBER.sub("", text, count=1)
    if text.startswith("【") and text.endswith("】"):
        text = text[1:-1]
    text = text.translate(str.maketrans("（），", "(),"))
    return re.sub(r"\s+", "", text).rstrip(":：").casefold()


def _rv_section_kind(section):
    if isinstance(section, (tuple, list)):
        parts = section
    else:
        parts = re.split(r"[ \t]+(?:/|>|›)[ \t]+", str(section or ""))
    keys = [_rv_heading_key(part) for part in parts]
    if any(_RV_HANDWRITTEN.fullmatch(key) for key in keys):
        return "handwritten"
    # 子标题不改变所属版本；路径中未识别的章节名不参与判定。
    for key in keys:
        if key in _RV_HEADINGS:
            return _RV_HEADINGS[key]
    return None


def _rv_raw_text(text):
    # 只剥行首的转写/制作标签；不改写标签之后的原话。
    dash = r'(?:-->|→|[-–—~～]|至)'
    sec = r'\d+(?:\.\d+)?'
    unit = r'(?:秒|secs?|s)'
    seconds = rf'{sec}[ \t]*(?:{unit}[ \t]*)?{dash}[ \t]*{sec}[ \t]*{unit}(?![A-Za-z])'
    clock_range = rf'{_RV_CLOCK}[ \t]*{dash}[ \t]*{_RV_CLOCK}(?![\d:：.,，．])'
    timing = rf'(?:{seconds}|{clock_range})'
    stage = (r'(?:开场(?:钩子)?|黄金三秒|钩子|铺垫|痛点|冲突|反转(?:[/／]观点)?|'
             r'观点|反共识立场|价值(?:输出|交付)?|解决方案|举例|案例|总结|收尾|'
             r'结尾|行动号召|互动引导|CTA)(?:[ \t]*[｜|][^\r\n]+|[（(][^\r\n]*[）)])?')
    cue = (r'(?:(?:场记|场景|镜头|画面|字幕|音效|配乐|转场|动作|表情|语气|'
           r'B[ -]?roll|SFX|BGM)(?:[ \t]*(?:\d+|[甲乙丙丁])|[ \t]*[:：][^\r\n]+)?|'
           r'停顿(?:[ \t]*\d+(?:\.\d+)?[ \t]*秒)?|略停|笑声|掌声|清嗓|咳嗽)')
    label = re.compile(rf'(?:{timing}(?:[ \t]+{stage})?|{stage}|{cue}|'
                       rf'{_RV_RANGE}|{_RV_SPEAKER}|主持人|旁白|嘉宾(?:\d+|[甲乙丙丁])?)', re.I)
    bracket = re.compile(r'^[ \t]*(?:【([^】]*)】|\[([^\]]*)\]|（([^）]*)）|\(([^)]*)\))')
    timed_label = re.compile(rf'{timing}[ \t]+[^ \t\r\n][^\r\n]{{0,63}}', re.I)
    bracket_time = re.compile(rf'(?:{timing}|{_RV_RANGE})', re.I)
    emoji_speaker = re.compile(
        rf'^[ \t]*[🔴🔵🟠🟡🟢🟣🟤⚪⚫🟥🟦🟧🟨🟩🟪🟫⬜⬛🎙🎤]\ufe0f?[ \t]*'
        rf'(?:{_RV_SPEAKER}|我|本人|作者|对方|主持人|旁白|采访者|受访者|嘉宾(?:\d+|[甲乙丙丁])?)'
        rf'[ \t]*(?:[:：][ \t]*)?', re.I,
    )
    emoji_stamp = re.compile(_RV_RANGE, re.I)
    # 旧 time_prefix 会误剥「15–40秒就是我愿意等的时间」；裸时间须独占一行或有显式分隔符。
    naked_time = re.compile(rf'^[ \t]*(?:{timing}|{_RV_CLOCK})(?=[ \t]*(?:$|[|｜]|[:：](?!\d)))', re.I)
    speaker = re.compile(r'^[ \t]*(?:主持人|旁白|采访者|受访者|嘉宾(?:\d+|[甲乙丙丁])?|'
                         r'[甲乙丙丁])(?:[ \t]*[:：])', re.I)
    named_speaker = re.compile(rf'^[ \t]*{_RV_SPEAKER}(?=[ \t]*(?:$|[:：|｜]|[\[【（(]|\d))', re.I)
    slate = re.compile(r'^[ \t]*(?:场记|场次|镜头)[ \t]*[:：]?[ \t]*(?:第[ \t]*)?'
                       r'(?:\d+|[一二三四五六七八九十]+)(?:[ \t]*(?:场|镜|条))?[ \t]*(?=$|[:：|｜])')
    separator = re.compile(r'[ \t]*(?:[:：|｜][ \t]*)?')
    wrapper = re.compile(r'^[ \t]*(\*\*|__|`)')

    def prefix(line):
        tagged = emoji_speaker.match(line)
        if tagged:
            stamp = bracket.match(line[tagged.end():])
            if stamp and emoji_stamp.fullmatch(next(s for s in stamp.groups() if s is not None).strip()):
                return separator.match(line, tagged.end() + stamp.end()).end()
        match = bracket.match(line)
        if match:
            inside = next(s for s in match.groups() if s is not None).strip()
            if label.fullmatch(inside) or timed_label.fullmatch(inside):
                return separator.match(line, match.end()).end()
        for pattern in (slate, naked_time, speaker):
            match = pattern.match(line)
            if match:
                return separator.match(line, match.end()).end()
        match = named_speaker.match(line)
        if match:
            tail = line[match.end():]
            if not tail.strip() or tail.lstrip(' \t').startswith((':', '：', '|', '｜')):
                return separator.match(line, match.end()).end()
            stamp = bracket.match(tail)
            if ((stamp and bracket_time.fullmatch(next(s for s in stamp.groups() if s is not None).strip()))
                    or (tail.startswith((' ', '\t')) and naked_time.match(tail))):
                return match.end()
        return 0

    # 奇数下标仍是原换行符；独占一行的标签变为空行。
    parts = _RV_NEWLINE.split(text)
    for i in range(0, len(parts), 2):
        line = parts[i]
        while line:
            wrapped = wrapper.match(line)
            if wrapped:
                mark = wrapped[1]
                stop = line.find(mark, wrapped.end())
                if stop >= 0:
                    inside = line[wrapped.end():stop]
                    n = prefix(inside)
                    if n and not inside[n:].strip():
                        line = line[separator.match(line, stop + len(mark)).end():]
                        continue
                    if n:
                        line = line[:wrapped.end()] + line[wrapped.end() + n:]
                        continue
            n = prefix(line)
            if not n:
                break
            line = line[n:]
        parts[i] = line
    return ''.join(parts)

def _rv_has_body(text, kind):
    for line in _RV_NEWLINE.split(text):
        if not line.strip() or _technical(line):
            continue
        key = _rv_heading_key(line)
        if kind is not None and _RV_HEADINGS.get(key) == kind:
            continue
        if re.fullmatch(r"[ \t]*[-*_]{3,}[ \t]*", line):
            continue
        return True
    return False


def _readable_blocks(blocks):
    """派生阅读块；不修改原块，按物理行保留来源映射。"""
    transcript = re.compile(r'(?:完整版?|完整的|视频|短视频|成片|正式|最终|终版|可直接照读)*'
                            r'(?:口播逐字稿|视频逐字稿|逐字口播稿|逐字稿|口播正文|口播全文)'
                            r'(?:\([^\n]*\))?')
    aside = {
        'selection': r'选题(?:分析|拆解|策略|定位|依据|为什么能爆)|为什么(?:这个)?选题能爆|爆款(?:要素|分析|拆解)',
        'formula': r'选题公式|爆款公式',
        'audience': r'目标受众(?:分析)?|受众(?:分析|画像)|用户画像|传播策略',
        'planning': r'创作(?:策划|思路)|内容策划|脚本结构|内容结构|五段式结构|口播(?:大纲|提纲)|脚本(?:大纲|提纲)|叙事结构',
        'packaging': r'标题(?:备选|方案|建议|设计)|封面(?:标题|文案|设计|建议)|标题(?:与|和|及|[/／+])封面|(?:发布|平台)文案|话题标签',
        'production': r'拍摄(?:建议|清单|方案|脚本)|剪辑(?:建议|清单|方案)|视觉(?:设计|建议)|画面(?:设计|建议)|分镜(?:脚本|设计|表)?|素材清单',
        'release': r'发布(?:前)?(?:检查(?:清单|表)?|清单|策略|计划|建议|准备|设置)|上线(?:检查)?清单|评论区(?:运营|引导|置顶)|互动策略',
        'platform': r'平台信息|数据(?:复盘|表现|统计)|发布数据',
        'references': r'事实与引用边界|参考资料|素材来源|合规(?:检查|标注)',
    }
    asides = [(kind, re.compile(rf'(?:{pattern})(?:\([^\n]*\))?'))
              for kind, pattern in aside.items()]
    md_heading = re.compile(r'^[ \t]*(#{1,6})[ \t]+')
    path_sep = re.compile(r'[ \t]+(?:/|>|›|->|→)[ \t]+')
    formula = re.compile(r'^[ \t>*_]*(?:选题公式|爆款公式)[*_ \t]*[:：]')

    def heading(value):
        key = _rv_heading_key(_plain(_RV_NUMBER.sub('', _plain(value), count=1)))
        if transcript.fullmatch(key):
            return 'transcript'
        return next((name for name, pattern in asides if pattern.fullmatch(key)), None)

    def spoken(line, kind):
        plain = _plain(line).lstrip('> ').strip('* ')
        return (bool(plain) and not _technical(plain)
                and not plain.startswith('|')
                and not re.match(r'^[-*+]\s+\[[ xX]\]', plain)
                and _rv_has_body(line, kind))

    rows = []
    plan_blocks = []
    plan_evidence = set()
    plan_has_body = False
    last_path = None
    active = None
    script_level = None
    populated = set()
    has_correction_table = False

    for block in blocks:
        section = block.get('section')
        kind = _rv_section_kind(section)
        original = block.get('text')
        text = original if isinstance(original, str) else ''
        reading = _rv_raw_text(text)
        has_body = _rv_has_body(reading, kind)
        if has_body:
            populated.add(kind)
        if kind == 'corrections' and _RV_ASR_TABLE.search(text):
            has_correction_table = True
        rows.append((block, kind, original, reading, has_body))

        path = tuple(str(p) for p in section) if isinstance(section, (list, tuple)) else tuple(path_sep.split(str(section or '')))
        path_kinds = [k for part in path if (k := heading(part)) is not None]
        plan_evidence.update(k for k in path_kinds if k != 'transcript')
        if path != last_path:
            active = next(iter(path_kinds), None)
            script_level = None
            last_path = path

        source_lines = _RV_NEWLINE.split(text)[::2]
        derived = _RV_NEWLINE.split(reading)
        first = None
        stop = len(source_lines) - int(bool(text) and text.endswith(('\r', '\n')))
        for i in range(stop + 1):
            keep = False
            if i < stop:
                source_line = source_lines[i]
                level = md_heading.match(source_line)
                area = heading(source_line)
                if source_line.strip() and _technical(source_line):
                    # 技术注释即使带 # 也不结束逐字稿；该源行只留空位。
                    keep = active == 'transcript'
                    if keep:
                        derived[2 * i] = ''
                elif area is not None:
                    active = area
                    script_level = len(level[1]) if area == 'transcript' and level else None
                    if area == 'transcript':
                        keep = True
                        derived[2 * i] = ''
                    else:
                        plan_evidence.add(area)
                elif formula.match(source_line):
                    plan_evidence.add('formula')
                    active = 'formula'
                    script_level = None
                elif active == 'transcript':
                    if level and script_level is not None and len(level[1]) <= script_level:
                        active = None
                        script_level = None
                    else:
                        keep = True
                        plan_has_body |= spoken(derived[2 * i], kind)
            if keep and first is None:
                first = i
            elif not keep and first is not None:
                start = int(block['start'])
                plan_blocks.append({**block, 'start': start + first, 'end': start + i - 1,
                                    'text': ''.join(derived[2 * first:2 * i - 1])})
                first = None

    # 单个关键词或一个逐字稿标题不足以判定整篇是策划案。
    # 逐字稿没有可读正文时，沿用普通阅读路径，不用空选区替换整篇。
    if len(plan_evidence) >= 2 and plan_has_body:
        return plan_blocks

    has_formal = bool(populated & _RV_FORMAL)
    has_main = 'main' in populated
    has_segmented_final = 'final_segmented' in populated
    has_raw_full = 'raw_full' in populated
    result = []
    for block, kind, original, reading, has_body in rows:
        if kind == 'final_continuous' and has_segmented_final:
            continue
        if kind in _RV_RAW:
            if has_formal or has_main:
                continue
            if kind == 'raw_timed' and has_raw_full:
                continue
            if not has_body and not reading.strip():
                continue
        if kind == 'corrections' and (has_formal or has_main or has_correction_table):
            continue
        if kind == 'metadata' and (has_formal or has_main or populated & _RV_RAW):
            continue
        if kind == 'citation_metadata':
            continue
        copied = dict(block)
        if isinstance(original, str) and reading != original:
            copied['text'] = reading
        result.append(copied)
    return result

def _technical(s):
    # 只判断当前物理行。去掉 Markdown 外壳是为了识别字段，不是为了隐藏普通引用。
    if '\r' in s or '\n' in s:
        return False
    s = _plain(re.sub(r'^(?:[ \t]*[>#＞＃]+[ \t]*)+', '', s))
    s = re.sub(r'^(\*\*|__)([^:：]+?)\1(?=[ \t]*[:：])', r'\2', s)
    if re.fullmatch(
        r'(?:源\s*[:：]\s*(?:视频号|公众号|抖音|B站|小红书)(?:平台)?\s*后台'
        r'.*(?:object[ _-]?id|自动转写|faster[- ]whisper).*'
        r'|转写状态\s*[:：]\s*(?:raw[_ -]asr(?:[_ -][a-z0-9]+)*|待校订|待人工校订|未校订|已校订|待复核)'
        r'\s*(?:[（(].*|[，,；;。].*)?'
        r'|生成方式\s*[:：]\s*(?:取|从|由|根据|基于|使用|采用).*'
        r'(?:标记稿|逐字稿|校订稿|删改稿|faster[- ]whisper).*'
        r'|说明\s*[:：]\s*(?:原始\s*(?:逐字稿|ASR)|逐条删改理由|校订(?:依据|记录|明细))'
        r'.*(?:见|查阅).*(?:来源文件|源文件|原始文件|校订表|\.md\b).*'
        r'|校订原则\s*[:：]\s*(?:(?:只|仅)(?:修正|纠正|订正|校正|改正|调整|修改)'
        r'\s*(?:ASR|错字|专名|标点|明显(?:的)?转写错误)|(?:保留|不改写)\s*(?:原话|口语|语序|原意)).*'
        r'|与(?:视频号|公众号|抖音|B站|小红书)(?:版本?)?为同一条视频\s*[，,；;、]?\s*'
        r'共享\s*`?WRK[-_][a-z0-9][a-z0-9_-]*.*'
        r'|既有策划稿\s*[:：]\s*.*\.md\b.*'
        r'|(?:平台版本映射|来源\s*ID)\s*[:：]\s*\S.*)',
        s, re.I,
    ):
        return True
    return bool(_META.fullmatch(s) or _EMPTY_TITLE.fullmatch(s)
                or re.match(r'^(?:资产性质|源文件|文件路径|本地路径|来源文件|转写说明|原始文件|录入说明|原文链接|素材路径|原视频|作者身份)\s*[：:（(]', s)
                or re.match(r'^(?:转写[：:]\s*(?:faster[- ]whisper|whisper)|[⚠️\s]*ASR\s*文本[，,（(]\s*(?:未校订|待校订|仅供校订|含(?:有)?识别噪声|未经人工(?:校订|核对))|原始\s*ASR\s*(?:与时间戳分段见|及校订依据见|[：:])|(?:证据入口|源视频|发布平台|发布时间|转写日期|平台|同源视频号版本|发布记录|音频文件|原始转写|转写工具|校订依据|作品编号)\s*[：:]|与视频号版本为同一条视频|视频号实际使用同一标题并发布于)', s, re.I)
                or s in {'', '---'}
                or (_ARCHIVE.match(s) and not _ARCHIVE.sub('', s, count=1)))


def readable_blocks(item):
    """返回阅读投影；块内空行保留源行位置，不另外切断朗读。"""
    result = []
    title = item['title'].strip()
    for b in _readable_blocks(item['blocks']):
        start = int(b['start'])
        text = b['text']
        lines = _RV_NEWLINE.split(text)[::2]
        if text.endswith(('\r', '\n')) and start + len(lines) - 1 > int(b['end']):
            lines.pop()
        first = 0
        stop = len(lines)
        hidden = set()
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            label = _plain(line).lstrip('> ').strip('* ')
            if (_technical(label) or (line.lstrip().startswith('#') and
                                      (label == title or _ARCHIVE.match(label)))):
                lines[i] = ''
                hidden.add(i)
        while first < stop and first in hidden:
            first += 1
        while stop > first and stop - 1 in hidden:
            stop -= 1
        if any(line.strip() for line in lines[first:stop]):
            result.append({**b, 'start': start + first, 'end': start + stop - 1,
                           'text': '\n'.join(lines[first:stop])})
    return result

def _title(title, preview):
    label = _ARCHIVE.sub("", _clean_title(title), count=1).strip()
    label = re.sub(r"^LOCAL-[\d-]+[_ ]*|__GN-[\w-]+$|[_＿](?:已发布视频逐字稿|微信公众号定稿|公众号版|短视频文案|视频号稿)$", "", label, flags=re.I).strip()
    if not label or _technical(label):
        return _plain(preview)[:48] or preview[:48]
    return label


def _norm(s):
    return unicodedata.normalize("NFKC", s).casefold()


def _quote_key(s):
    return _QUOTE_PUNCT.sub("", _norm(s))


def _matcher(terms):
    patterns = []
    for term in dict.fromkeys(_norm(x.strip()) for x in terms if x.strip()):
        pattern = re.escape(term)
        if term[0].isascii() and term[0].isalnum():
            pattern = r"(?<![a-z0-9])" + pattern
        if term[-1].isascii() and term[-1].isalnum():
            pattern += r"(?![a-z0-9])"
        patterns.append(pattern)
    return re.compile("|".join(patterns)) if patterns else None


class _Classifier:
    def __init__(self, mapping):
        self.topics = {}
        self.patterns = {}
        for entry in mapping.get("topics", []):
            tid = entry["id"]
            if entry["domain"] not in _DOMAINS or not tid:
                continue
            if tid in self.topics:
                raise ValueError(f"四域归类话题 ID 重复：{tid}")
            self.topics[tid] = entry
            self.patterns[tid] = _matcher([entry["title"], *entry.get("terms", [])])
        self.dom_patterns = {d: _matcher(words) for d, words in _DOMAIN_TERMS.items()}
        self.sources = mapping.get("sources", {})

    def labels(self, text, sid=None, digest=None):
        saved = self.sources.get(sid)
        if saved is not None and digest and saved.get("hash") == digest:
            ds = set(saved.get("domains", []))
            ts = set(saved.get("topics", []))
        else:
            text = _norm(text)
            ds = {d for d, p in self.dom_patterns.items() if p.search(text)}
            ts = {t for t, p in self.patterns.items() if p and p.search(text)}
        topics = [t for t in self.topics if t in ts]
        ds.update(self.topics[t]["domain"] for t in topics)
        return [d for d in _DOMAINS if d in ds], topics


def _stamp(path):
    try:
        st = path.stat()
        return [st.st_mtime_ns, st.st_size, st.st_ctime_ns, st.st_mode,
                st.st_dev, st.st_ino, os.access(path, os.R_OK)]
    except _LOCAL_ERRORS as exc:
        return ["unavailable", exc.errno]


def _stamps(paths):
    return {str(p): _stamp(Path(p)) for p in paths}


def _base(lib, mapping):
    script = Path(lib.profile.get("core_root", "")) / "yl-knowledge-search/scripts/retrieval.py"
    return {
        "files": _stamps((lib.manifest, lib.state, lib.expressions / "历次出处.md",
                          mapping, script)),
        "reader": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "profile": hashlib.sha256(json.dumps(
            lib.profile, ensure_ascii=False, sort_keys=True
        ).encode()).hexdigest(),
        "root": str(lib.root),
        
    }


def _build(lib, mapping):
    classifier = _Classifier(mapping)
    edits = lib.edits()
    sources = {}
    paths = defaultdict(list)
    works = {}
    ranges = {}
    counts = defaultdict(set)
    for sid, row in lib.active_sources().items():
        if sid in edits["removed"] or not row.get("index", True):
            continue
        try:
            body = lib._body(row)
            path = os.path.normcase(str(Path(row["path"]).resolve()))
        except _LOCAL_ERRORS:
            continue
        except ValueError as exc:
            if exc.args == ("来源已排除",):
                continue
            raise
        blocks = readable_blocks(body)
        if not blocks:
            continue
        text = "\n".join(b["text"] for b in blocks)
        pure = "".join(text.split())
        preview = " ".join(text[:512].split())[:180]
        title = _title(body["title"], preview)
        ds, ts = classifier.labels(title + "\n" + text, sid, body["hash"])
        if ts:
            finger = hashlib.sha256(pure.encode()).digest()
            for tid in ts:
                counts[tid].add(finger)
        works[sid] = dict(source_id=sid, title=title, preview=preview,
                          characters=len(pure), domains=ds, topics=ts)
        sources[sid] = row
        paths[path].append(sid)
        blocks.sort(key=lambda b: b["start"])
        ranges[sid] = ([b["start"] for b in blocks], blocks)

    visible = {t for t, bodies in counts.items() if len(bodies) >= 2}
    topic_work_counts = defaultdict(int)
    for work in works.values():
        work["topics"] = [t for t in work["topics"] if t in visible]
        for tid in work["topics"]:
            topic_work_counts[tid] += 1

    def locate(qid, sid, text, line):
        if not text.strip() or sid not in sources:
            return None
        hit = lib._resolve(dict(id=qid, source_id=sid, text=text, start_line=line),
                           sources, paths)
        if not hit:
            return None
        start = hit["start_line"]
        starts, blocks = ranges[sid]
        i = bisect_right(starts, start) - 1
        def positions(block):
            body = block["text"]
            pos = body.find(text)
            while pos >= 0:
                yield block["start"] + body.count("\n", 0, pos)
                pos = body.find(text, pos + 1)
        if i < 0 or start not in positions(blocks[i]):
            alternatives = [(j, n) for j,b in enumerate(blocks) for n in positions(b)]
            if len(alternatives) != 1:
                return None
            i, start = alternatives[0]
        return dict(source_id=sid, source_title=works[sid]["title"],
                    start_line=start, text=text, context=blocks[i]["text"])

    rejected = {_quote_key(q["text"]) for q in edits["rejected"].values()}
    quotes = []
    for qid, q in lib._all_quotes(edits).items():
        text = q["text"]
        if not text.strip() or _quote_key(text) in rejected:
            continue
        candidates = []
        if "source_id" in q:
            if q["source_id"] not in sources:
                continue
            candidates.append((q["source_id"], text, q.get("start_line", 0)))
        for variant, path, line in q.get("refs", []):
            candidates.extend((sid, variant, line) for sid in paths.get(os.path.normcase(path), ()))
        for v in q.get("variants", []):
            candidates.append((v["source_id"], v["text"], v.get("start_line", 0)))
        hits = {}
        for sid, variant, line in sorted(dict.fromkeys(candidates), key=lambda c: c[1] != text):
            if _quote_key(variant) in rejected:
                continue
            hit = locate(qid, sid, variant, line)
            if hit:
                hits.setdefault((sid, hit["start_line"], variant), hit)
        located = list(hits.values())
        main = located[0] if located else {}
        selected = qid in edits["added"]
        status = "unverified"
        if located:
            status = ("variant" if main["text"] != text else
                      "candidate" if not selected and q.get("status") == "candidate"
                      else "verified")
            ds = {d for h in located for d in works[h["source_id"]]["domains"]}
            ts = {t for h in located for t in works[h["source_id"]]["topics"]}
        else:
            ds, ts = classifier.labels(text)
        quotes.append(dict(
            id=qid, text=text, status=status, selected=selected,
            source_id=main.get("source_id"), source_title=main.get("source_title"),
            start_line=main.get("start_line"), actual_text=main.get("text"),
            context=main.get("context", ""),
            domains=[d for d in _DOMAINS if d in ds],
            topics=[t for t in classifier.topics if t in ts and t in visible],
            variants=[{k: v for k, v in h.items() if k != "context"} for h in located
                      if h is not main or main["text"] != text],
        ))
    quotes.sort(key=lambda q: (not q["selected"], q["status"] != "candidate", not q["source_id"]))
    domains = [
        dict(id=d, title=name, topics=[
            dict(id=t, title=entry["title"], count=topic_work_counts[t])
            for t, entry in classifier.topics.items() if t in visible and entry["domain"] == d
        ]) for d, name in _DOMAINS.items()
    ]
    return dict(domains=domains, works=list(works.values()), quotes=quotes,
                stats=dict(works=len(works), quotes=len(quotes),
                           characters=sum(w["characters"] for w in works.values())),
                counting_note="作品数、话题篇数和非空白正文字符均按实际可浏览的作品统计，不合并版本；"
                              "话题至少包含两份独立正文才显示（阅读正文去空白后按 SHA-256 判重），判重不影响显示的篇数。")


def catalog(lib) -> dict:
    """返回独立的展示投影，不获取第二把锁，也不写入正文、归类或编辑记录。"""
    mapping = lib.store / "四域归类.json"
    cache = lib.store / "浏览索引.cache.json"
    base = _base(lib, mapping)
    try:
        saved = _load(cache)
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        saved = None
    if (isinstance(saved, dict) and saved.get("schema") == _SCHEMA
            and saved.get("base") == base and isinstance(saved.get("watch"), dict)
            and isinstance(saved.get("data"), dict)
            and _stamps(saved["watch"]) == saved["watch"]):
        return saved["data"]

    # manifest 在这里仅提供失效依赖，不授予读取正文的权限。也监视本次
    # active_sources 因文件暂缺或权限不足未返回的行，以便恢复后自动重建。
    watch = _stamps(dict.fromkeys(r["path"] for r in _load(lib.manifest)["sources"]
                                  if r.get("path")))
    try:
        rules = _load(mapping)
    except FileNotFoundError:
        rules = {}
    data = _build(lib, rules)
    if base == _base(lib, mapping) and watch == _stamps(watch):
        _atomic(cache, dict(schema=_SCHEMA, base=base, watch=watch, data=data))
    return data