# reading_info.py
"""只从当前作品的正文和来源行提取明确记载的摘要与发布指标。"""

import math
import re
from collections.abc import Mapping
from itertools import groupby
from pathlib import Path
from types import FunctionType


def _words(text):
    return frozenset(text.split())


_PLATFORMS = _words(
    "抖音 快手 视频号 微信视频号 公众号 微信公众号 订阅号 微信订阅号 "
    "小红书 B站 哔哩哔哩 bilibili 微博 今日头条 头条号 西瓜视频 "
    "百家号 百度百家号 知乎 知乎视频 豆瓣 即刻 大鱼号 网易号 "
    "腾讯新闻 腾讯视频 搜狐号 企鹅号 UC大鱼号 皮皮虾 "
    "YouTube YouTube Shorts TikTok Instagram Instagram Reels "
    "Facebook Facebook Reels X Twitter Threads LinkedIn Twitch Vimeo"
) | {"YouTube Shorts", "Instagram Reels", "Facebook Reels"}
# 带空格的全名可以匹配；不把 Shorts、Reels 当成独立平台。
_PLATFORMS -= {"Shorts", "Reels"}
_PLATFORM_NAMES = {name.casefold(): name for name in _PLATFORMS}
_TOTALS = _words("聚合 汇总 合计 总计 全平台 跨平台 aggregate overall total all_platforms")

_METRIC_NAMES = _words(
    "播放 播放量 播放数 播放次数 观看量 观看数 观看次数 观看人数 "
    "有效播放量 有效播放数 重复播放量 阅读量 阅读数 阅读次数 阅读人数 "
    "阅读 浏览量 浏览数 浏览次数 浏览人数 展现量 展现数 展现次数 "
    "曝光量 曝光数 曝光次数 曝光人数 推荐量 推荐次数 触达量 触达人数 "
    "点击量 点击数 点击次数 点击人数 点击率 播放率 阅读率 打开率 "
    "点赞 点赞量 点赞数 点赞次数 点赞率 点赞人数 获赞数 "
    "评论 评论量 评论数 评论次数 评论人数 评论率 "
    "收藏 收藏量 收藏数 收藏次数 收藏人数 收藏率 "
    "转发 转发量 转发数 转发次数 转发人数 转发率 "
    "分享 分享量 分享数 分享次数 分享人数 分享率 "
    "在看 在看数 在看量 在看人数 投币数 投币量 弹幕数 弹幕量 "
    "完播率 完播量 完播数 完播人数 平均播放进度 平均观看进度 "
    "平均观看时长 平均播放时长 平均阅读时长 平均停留时长 "
    "观看时长 播放时长 阅读时长 总观看时长 总播放时长 总阅读时长 "
    "互动量 互动数 互动人数 互动率 新增关注 新增关注数 关注数 "
    "关注量 关注人数 关注率 涨粉 涨粉数 涨粉量 转粉数 转粉率 "
    "取关数 净增粉丝数 主页访问量 主页访问人数 主页访问次数 "
    "转化量 转化数 转化率 订单数 成交数 成交金额 销售额 GMV 收益 "
    "跳出率 留存率 首屏留存率 点赞收藏比"
)
_METRICS = {name.casefold(): name for name in _METRIC_NAMES}
_METRICS.update({
    "views": "播放量", "view_count": "播放量", "play_count": "播放量",
    "plays": "播放量", "reads": "阅读量", "read_count": "阅读量",
    "impressions": "曝光量", "impression_count": "曝光量",
    "reach": "触达人数", "likes": "点赞数", "like_count": "点赞数",
    "comments": "评论数", "comment_count": "评论数",
    "favorites": "收藏数", "favorite_count": "收藏数", "saves": "收藏数",
    "shares": "分享数", "share_count": "分享数",
    "reposts": "转发数", "repost_count": "转发数",
    "completion_rate": "完播率", "avg_watch_time": "平均观看时长",
    "watch_time": "观看时长", "clicks": "点击量", "ctr": "点击率",
    "engagement_rate": "互动率", "new_followers": "新增关注数",
})
_PLATFORM_KEYS = _words("平台 发布平台 渠道 发布渠道 platform platform_name")
_TITLE_KEYS = _words("作品 作品名 作品名称 作品标题 发布标题 视频标题 文章标题 标题 title work_title")
_ID_KEYS = _words("来源ID 来源编号 source_id")
_FIELD_KEYS = _words("指标 指标名 指标名称 字段 项目 数据项 信息项 名称 metric label key")
_VALUE_KEYS = _words("值 数值 数据 指标值 内容 value")
_SIGNAL_KEYS = _words("爆款要素 选题公式 爆款公式")
_SIGNAL_COLUMNS = _words("本条落点 本作落点 作品落点 本条应用 具体落点 落点 内容")
_AGG_CONTAINERS = _words("aggregate_metrics aggregated_metrics 聚合指标 汇总指标 全平台数据")
_CONTAINERS = _AGG_CONTAINERS | _words(
    "metrics platform_metrics publication_metrics publishing_metrics "
    "platform_info publication_data publish_data 平台信息 平台数据 发布数据 发布指标"
)
_META_CONTAINERS = _words("metadata publication publishing publication_metadata 发布元信息")
_FOREIGN = re.compile(
    r"^(?:(?:同类|其他|其它|参考|竞品|对标|往期|历史|相关|示例|样例)"
    r"(?:的)?(?:作品|视频|文章|文案|数据|案例)|案例(?:库|对比|参考)|"
    r"其他作品|竞品分析|对标分析|数据对比|举例|模板(?:示例)?)(?:.*)$"
)
_DATA_HEADING = re.compile(
    r"^(?:各平台|分平台|跨平台|全平台|作品|视频|文章)?"
    r"(?:平台信息|平台数据|平台指标|发布信息|发布数据|发布指标|"
    r"出版数据|出版信息|发布表现|数据表现|传播数据|传播表现|运营数据|"
    r"数据复盘|数据统计|数据汇总|指标汇总|聚合指标)(?:[：:].*)?$"
)
_NUMBER = r"[+-]?(?:[0-9]{1,3}(?:[,，][0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_VALUE = re.compile(
    rf"(?:[¥￥$]?\s*{_NUMBER}\s*(?:[%％‰]|(?:千|万|亿|[kKmMbB])?"
    rf"(?:次|人次|人|个|条|笔|元|秒|分钟|小时|天)?)|"
    r"[0-9]+:[0-5][0-9](?::[0-5][0-9])?|"
    r"(?:[0-9]+小时)?(?:[0-9]+分(?:钟)?)?[0-9]+(?:\.[0-9]+)?秒)"
)
_SECTION_NO = re.compile(r"^(?:[一二三四五六七八九十百]+[、.．]|[0-9]+[、.．)])\s*")
_IP = re.compile(
    r"账号\s*IP\s*定位|(?:个人|账号|品牌)?\s*IP\s*定位|"
    r"IP\s*(?:灵魂|人设|标签|画像|调性)|人设定位|账号定位",
    re.IGNORECASE,
)


def _clean(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"</?(?:strong|em|b|i|code|span)\b[^>]*>", "", value, flags=re.I)
    value = re.sub(r"(`+|\*\*|__|~~)(.+?)\1", r"\2", value)
    value = re.sub(r"(?<!\w)([*_])(\S(?:.*?\S)?)\1(?!\w)", r"\2", value)
    value = re.sub(r"\\([\\|*_`])", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def _key(value):
    return _clean(value).rstrip(":：").strip().casefold()


def _platform(value):
    return _PLATFORM_NAMES.get(_key(value))


def _group(value):
    return _platform(value) or ("聚合" if _key(value) in _TOTALS else None)


def _metric(key):
    key = _key(key)
    label = _METRICS.get(key)
    if label:
        return label
    # 明确的总量仍保留原字段中的“总”，不与单次指标合并。
    if key.startswith(("总", "累计")):
        prefix = "累计" if key.startswith("累计") else "总"
        if key[len(prefix):] in _METRICS:
            return _clean(key)
    return None


def _value(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        if not math.isfinite(raw):
            return None
        raw = str(raw)
    text = _clean(raw)
    return text if _VALUE.fullmatch(text) else None


def _pairs_match(pairs, title, sid):
    for key, value in pairs:
        key = _key(key)
        if key in _TITLE_KEYS and (not title or _clean(value) != title):
            return False
        if key in _ID_KEYS and (sid is None or value != sid):
            return False
    return True


def _declared_group(pairs):
    values = [_group(value) for key, value in pairs if _key(key) in _PLATFORM_KEYS]
    if not values:
        return False, None
    return True, values[0] if all(value == values[0] for value in values) else None


def _highlight(raw):
    text = _clean(raw)
    text = re.sub(
        r"[（(]\s*(?:(?:个人|账号|品牌)?\s*IP\s*(?:定位|灵魂|人设|标签|画像|调性)"
        r"|人设定位|账号定位)\s*[）)]", "", text, flags=re.I,
    )
    text = _IP.sub("", text)
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" \t:：|·-—×、，。；;")
    # 不截断，也不把多条落点拼成一条。
    return text if 2 <= len(text) <= 96 and re.search(r"[\w\u4e00-\u9fff]", text) else None


def _unquote(line):
    return re.sub(r"^(?:\s*>\s*)+", "", line).strip()


def _kv(line):
    line = re.sub(r"^(?:[-+*]\s+|\d+[.)、]\s+)", "", _unquote(line))
    if line.startswith("[") or line.startswith("|"):
        return None
    # 兼容 **指标：** 数值、**指标**：数值和 **指标：数值**。
    line = re.sub(r"^(\*\*|__)([^:：]+)([:：])\1", r"\2\3", line)
    line = _clean(line)
    match = re.fullmatch(r"([^:：|]{1,40})\s*[:：]\s*(.*)", line)
    return (match[1].strip(), match[2].strip()) if match else None


def _cells(line):
    line = _unquote(line)
    if not line or "|" not in line or line[0] in "`#":
        return None
    # GFM 的表格允许转义竖线；内部空单元格不能丢弃。
    parts = re.split(r"(?<!\\)\|", line)
    if parts and not parts[0].strip():
        parts.pop(0)
    if parts and not parts[-1].strip():
        parts.pop()
    return [_clean(part) for part in parts] if len(parts) >= 2 else None


def _separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _heading(line):
    line = _unquote(line)
    match = re.fullmatch(r"(#{1,6})\s+(.+?)(?:\s+#+)?", line)
    if match:
        return len(match[1]), _SECTION_NO.sub("", _clean(match[2])).rstrip("：:")
    text = _clean(line)
    stripped = _SECTION_NO.sub("", text).rstrip("：:")
    if _kv(line) and _kv(line)[1]:
        return None
    if stripped and (_group(stripped) or _DATA_HEADING.fullmatch(stripped)
                     or _FOREIGN.fullmatch(stripped) or stripped in _SIGNAL_KEYS):
        return (2 if text != _SECTION_NO.sub("", text) else 3), stripped
    if text != _SECTION_NO.sub("", text) and re.match(r"^[一二三四五六七八九十]+[、.．]", text):
        return 2, stripped
    return None


def _sections(text):
    """产生带父标题的正文片段；代码围栏内的示例不作为发布记录。"""
    stack, lines = [], []
    fence = None
    for line in text.splitlines():
        mark = re.match(r"^(`{3,}|~{3,})(.*)$", _unquote(line))
        if fence:
            if mark and mark[1][0] == fence[0] and len(mark[1]) >= len(fence) and not mark[2].strip():
                fence = None
            continue
        if mark:
            fence = mark[1]
            lines.append("")
            continue
        heading = _heading(line)
        if heading is None:
            lines.append(line)
            continue
        if lines:
            yield tuple(name for _, name in stack), lines
        level, name = heading
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, name))
        lines = []
    if lines:
        yield tuple(name for _, name in stack), lines


def _tokens(lines):
    i = 0
    while i < len(lines):
        cells = _cells(lines[i])
        next_cells = _cells(lines[i + 1]) if i + 1 < len(lines) else None
        if cells and (_separator(next_cells) or _unquote(lines[i]).startswith("|")):
            rows = [cells]
            i += 1
            while i < len(lines):
                cells = _cells(lines[i])
                if not cells:
                    break
                # 相邻的第二张带表头的表不能并入上一张表。
                following = _cells(lines[i + 1]) if i + 1 < len(lines) else None
                if _separator(following):
                    break
                rows.append(cells)
                i += 1
            yield "table", rows
            continue
        pair = _kv(lines[i])
        if pair:
            yield "kv", pair
        else:
            match = re.match(r"^\s*[-+*]\s+(?!\[[ xX]\])(.+)$", _unquote(lines[i]))
            if match:
                yield "bullet", match[1]
        i += 1


def _table(rows, ambient, title, sid, emit, add_highlight):
    header = [_key(cell) for cell in rows[0]]
    ruled = len(rows) > 1 and _separator(rows[1])
    body = rows[2:] if ruled else rows[1:]
    if not body and ruled:
        return

    if "爆款要素" in header or "选题公式" in header or "爆款公式" in header:
        signal = next(i for i, key in enumerate(header) if key in _SIGNAL_KEYS)
        concrete = next((i for i, key in enumerate(header) if key in _SIGNAL_COLUMNS), signal)
        for cells in body:
            if len(cells) == len(header) and _pairs_match(zip(header, cells), title, sid):
                add_highlight(cells[concrete])
        return

    # | 平台 | 作品标题 | 播放量 | 点赞数 |，逐行核验作品身份。
    platform_cols = [i for i, key in enumerate(header) if key in _PLATFORM_KEYS]
    metric_cols = [(i, _metric(key)) for i, key in enumerate(header) if _metric(key)]
    if metric_cols and (len(platform_cols) == 1 or (not platform_cols and ambient)):
        field_cols = [i for i, key in enumerate(header) if key in _FIELD_KEYS]
        if not field_cols:
            for cells in body:
                if len(cells) != len(header) or not _pairs_match(zip(header, cells), title, sid):
                    continue
                group = _group(cells[platform_cols[0]]) if platform_cols else ambient
                for i, label in metric_cols:
                    emit(group, label, cells[i])
            return

    # | 指标 | 视频号 | 公众号 |。只按该列的明确表头归属。
    by_column = [(i, _group(cell)) for i, cell in enumerate(rows[0]) if i and _group(cell)]
    if by_column and (header[0] in _FIELD_KEYS | _PLATFORM_KEYS or not header[0]):
        if any(len(cells) != len(header) for cells in body):
            return
        for i, group in by_column:
            lineage = [(cells[0], cells[i]) for cells in body]
            if _pairs_match(lineage, title, sid):
                for key, value in lineage:
                    emit(group, _metric(key), value)
        return

    # | 字段 | 内容 |，也接受无表头的 | 播放量 | 0 |。
    if len(header) != 2:
        return
    recognized_header = header[0] in _FIELD_KEYS and header[1] in _VALUE_KEYS
    if ruled and not recognized_header:
        return
    pairs = body if recognized_header else rows
    if any(len(cells) != 2 for cells in pairs) or not _pairs_match(pairs, title, sid):
        return
    explicit, group = _declared_group(pairs)
    if not explicit:
        group = ambient
    for key, value in pairs:
        if _key(key) in _SIGNAL_KEYS:
            add_highlight(value)
        emit(group, _metric(key), value)


def _body_sections(item, row):
    blocks = item.get('blocks')
    if isinstance(blocks, (list, tuple)) and blocks:
        def section(block):
            return _clean(block.get('section')) if isinstance(block, Mapping) else ''

        for name, run in groupby(blocks, key=section):
            heading = _heading(name)
            name = heading[1] if heading else _SECTION_NO.sub('', name).rstrip('：:')
            prefix = (name,) if name else ()
            text = '\n'.join(block['text'].strip('\r\n') for block in run
                             if isinstance(block, Mapping) and isinstance(block.get('text'), str))
            for headings, lines in _sections(text):
                yield prefix + headings, lines
        return
    if not any(row.get(key) for key in ('allowed_spans', 'include_sections', 'exclude_sections')):
        text = item.get('text')
        if isinstance(text, str):
            yield from _sections(text)


def _canonical_group(root, item, row):
    if root is None or not item.get('path') or not row.get('path'):
        return None
    try:
        base = Path(root).resolve()
        path = Path(item['path']).resolve()
        if path != Path(row['path']).resolve():
            return None
        dirs = path.relative_to(base).parts[:-1]
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    known = {'02_视频号': '视频号', '01_公众号': '公众号'}
    platforms = {known[name] for name in dirs if name in known}
    return next(iter(platforms)) if len(platforms) == 1 else None


def _from_body(sections, source_group, title, sid, emit, add_highlight):
    for headings, lines in sections:
        if any(_FOREIGN.fullmatch(name) or re.match(r'^(?:案例|示例|样例|引用|转述|竞品|对标|他人|复用模板)', name)
               for name in headings):
            continue
        tokens = list(_tokens(lines))
        pairs = [data for kind, data in tokens if kind == "kv"]
        if not _pairs_match(pairs, title, sid):
            continue
        ambient = next((group for name in reversed(headings) if (group := _group(name))), None)
        data_section = any(_DATA_HEADING.fullmatch(name) for name in headings)
        metric_scope = bool(ambient or data_section)
        if not ambient and data_section:
            ambient = source_group
        metric_out = emit if metric_scope else (lambda *_: None)
        signal_section = bool(headings and headings[-1] in _SIGNAL_KEYS)
        group = ambient
        pending = False
        for kind, data in tokens:
            if kind == "table":
                _table(data, group, title, sid, metric_out, add_highlight)
                pending = False
            elif kind == "kv":
                key, value = data
                key = _key(key)
                pending = key in _SIGNAL_KEYS and not value
                if key in _PLATFORM_KEYS:
                    group = _group(value)
                elif key in _SIGNAL_KEYS:
                    add_highlight(value)
                else:
                    metric_out(group, _metric(key), value)
            elif signal_section or pending:
                add_highlight(data)


def _from_row(node, inherited, title, sid, emit, depth=0, keyed=False):
    if depth > 7:
        return
    if isinstance(node, (list, tuple)):
        for entry in node:
            _from_row(entry, inherited, title, sid, emit, depth + 1, keyed)
        return
    if not isinstance(node, Mapping) or not _pairs_match(node.items(), title, sid):
        return
    pairs = {_key(key): value for key, value in node.items() if isinstance(key, str)}
    explicit, group = _declared_group(node.items())
    if not explicit:
        group = inherited
    if not explicit and group is None and _key(pairs.get("scope")) in _TOTALS:
        group = "聚合"
    if keyed:
        label = next((_metric(pairs[key]) for key in ("label", "metric", "指标", "指标名")
                      if key in pairs), None)
        for key in ("value", "值", "数值", "指标值"):
            if key in pairs:
                emit(group, label, pairs[key])
                break
    for key, value in node.items():
        name = _key(key)
        label = _metric(name)
        if label:
            # 来源行的裸数需要平台；只有明确的合计字段才可无平台。
            target = group
            if target is None and not explicit and name.startswith(("总", "累计")):
                target = "聚合"
            emit(target, label, value)
        elif name in _CONTAINERS:
            target = "聚合" if name in _AGG_CONTAINERS else group
            _from_row(value, target, title, sid, emit, depth + 1, True)
        elif name in _META_CONTAINERS:
            _from_row(value, group, title, sid, emit, depth + 1)
        elif name in {"platforms", "平台分组", "by_platform"}:
            _from_row(value, group, title, sid, emit, depth + 1, True)
        elif keyed and _group(key):
            _from_row(value, _group(key), title, sid, emit, depth + 1, True)


def reading_info(item, row, *, root=None):
    """返回该作品的原文短要素与发布指标，数值以原有单位的字符串展示。"""
    result = {"highlights": [], "metrics": []}
    if not isinstance(item, Mapping) or not isinstance(row, Mapping):
        return result
    item_id, row_id = item.get("source_id"), row.get("source_id")
    if item_id is not None and row_id is not None and item_id != row_id:
        return result
    sid = item_id if item_id is not None else row_id
    title = _clean(item.get("title") or row.get("title"))
    if not _pairs_match(row.items(), title, sid):
        return result

    seen = set()
    body_keys = set()

    def emit(platform, label, raw, *, from_body=True):
        if not platform or not label:
            return
        value = _value(raw)
        if value is None:
            return
        metric_key = (platform, label)
        record = (*metric_key, value)
        if not from_body and metric_key in body_keys:
            return
        if record not in seen:
            seen.add(record)
            result["metrics"].append({"platform": platform, "label": label, "value": value})
        if from_body:
            body_keys.add(metric_key)

    def add_highlight(raw):
        highlights = result["highlights"]
        if len(highlights) < 2:
            text = _highlight(raw)
            if text and text not in highlights:
                highlights.append(text)

    declared, source_group = _declared_group(row.items())
    body_group = source_group if declared else _canonical_group(root, item, row)
    _from_body(_body_sections(item, row), body_group, title, sid, emit, add_highlight)
    _from_row(
        row, source_group, title, sid,
        lambda platform, label, raw: emit(platform, label, raw, from_body=False),
    )
    return result


_PLATFORM_EQUIV = {
    'wechatchannels': '视频号', 'wechat_channels': '视频号', 'xiaohongshu': '小红书', 'douyin': '抖音', 'wechat_official_account': '公众号', '微信公众号': '公众号', '微信视频号': '视频号',
    '哔哩哔哩': 'b站', 'bilibili': 'b站',
}
_LABEL_EQUIV = {
    variant: names.split()[0]
    for names in (
        '播放量 播放 播放数 播放次数', '阅读量 阅读 阅读数 阅读次数',
        '点赞数 点赞 点赞量 点赞次数', '评论数 评论 评论量 评论次数',
        '收藏数 收藏 收藏量 收藏次数', '转发数 转发 转发量 转发次数',
        '分享数 分享 分享量 分享次数', '在看数 在看 在看量',
        '曝光量 曝光数 曝光次数', '展现量 展现数 展现次数',
        '浏览量 浏览数 浏览次数', '点击量 点击数 点击次数',
        '互动量 互动数',
    )
    for variant in names.split()
}
_PLATFORM_EDITION = re.compile(
    r'\s*[（(](?:\d{4}(?:[-/.年]\d{1,2}){1,2}日?|第\s*\d+\s*期)[）)]$'
)


def _merge_key(record):
    platform = _clean(record['platform']).split(' · ', 1)[0]
    platform = _key(_PLATFORM_EDITION.sub('', platform))
    label = _key(_clean(record['label']).split(' · ', 1)[0])
    label = _metric(label) or label
    return _PLATFORM_EQUIV.get(platform, platform), _LABEL_EQUIV.get(label, label)


def merge_metrics(original, ledger):
    # 台账已按发布记录选取最新快照；显示时保留帖、期次和日期。
    result, seen, covered = [], set(), set()
    for records, authoritative in ((ledger, True), (original, False)):
        for record in records:
            if not authoritative and _merge_key(record) in covered:
                continue
            value = record['value']
            if value is None or value == '':
                continue
            if authoritative:
                covered.add(_merge_key(record))
            exact = (record['platform'], record['label'], str(value))
            if exact not in seen:
                seen.add(exact)
                result.append(record)
    return result


def publication_data(root, item, row, *, with_watch, profile=None):
    from publication import published_metrics, watch_reading_files

    if not with_watch:
        return published_metrics(root, item, row, profile=profile), ()

    metrics = published_metrics(root, item, row, profile=profile)
    return metrics, tuple(str(path) for path in watch_reading_files(root, item, row, profile=profile))
