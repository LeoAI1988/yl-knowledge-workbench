import csv as _rpm_csv
import datetime as _rpm_dt
import hashlib as _rpm_hashlib
import json as _rpm_json
import math as _rpm_math
import os as _rpm_os
import re as _rpm_re
import tempfile as _rpm_tempfile
import time as _rpm_time
from collections import defaultdict as _rpm_defaultdict
from collections.abc import Mapping as _rpm_Mapping
from pathlib import Path as _rpm_Path


_RPM_READING = _rpm_Path("90_系统资料/系统导航/07_阅读入口")
_RPM_TABLES = (
    ("publication", "发布记录.csv"),
    ("performance", "内容表现.csv"),
    ("retention", "内容留存.csv"),
    ("conversion", "业务转化.csv"),
)
_RPM_INDEX_REFRESH_SECONDS = 60
_RPM_ID_FIELDS = {
    "asset_id": "asset",
    "work_id": "work",
    "publication_id": "publication",
    "object_id": "review_object",
    "legacy_object_id": "review_object",
}
_RPM_ASSET_ID = _rpm_re.compile(r"ASR-\d{8}-R\d+")
_RPM_VIDEO_PLATFORMS = {
    "视频号", "微信视频号", "wechat channels", "wechat_channels", "wechat-channels",
}
_RPM_METRICS = {
    "performance": {
        "impressions": "曝光", "views": "播放", "reads": "阅读",
        "unique_readers": "独立读者", "click_through_rate": "点击率",
        "completion_rate": "完播率", "avg_watch_seconds": "平均播放时长",
        "likes": "点赞", "comments": "评论", "favorites": "收藏",
        "shares": "分享", "recommendations": "推荐", "follows": "关注",
        "unfollows": "取关", "profile_visits": "主页访问",
        "link_clicks": "链接点击", "leads": "线索", "sales": "销售",
    },
    "retention": {
        "views": "播放", "avg_watch_seconds": "平均播放时长",
        "completion_rate": "完播率", "two_second_exit_rate": "两秒划走率",
        "five_second_exit_rate": "五秒划走率", "follows": "关注",
        "follower_view_share": "粉丝观看占比",
    },
    "review": {
        name: name for name in (
            "播放", "完播率", "快速划走率", "三秒完播率", "平均播放时长",
            "关注", "点赞", "评论", "分享", "收藏", "万播放涨粉", "时长秒",
        )
    },
    "conversion": {
        "content_attributed_orders": "内容归因订单",
        "content_attributed_revenue": "内容归因收入",
    },
}


def _rpm_get(obj, key, default=None):
    if isinstance(obj, _rpm_Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _rpm_id(value):
    if isinstance(value, str):
        return value.strip()
    if type(value) is int:
        return str(value)
    return ""


def _rpm_platform(value):
    text = _rpm_id(value)
    return "视频号" if text.casefold() in _RPM_VIDEO_PLATFORMS else text


def _rpm_vault_path(root, value):
    """仅接受可解析到 vault 内的真实路径；不按文件名或路径后缀反查。"""
    if not isinstance(value, (str, _rpm_os.PathLike)) or not str(value).strip():
        return None
    try:
        path = _rpm_Path(value)
        path = (path if path.is_absolute() else root / path).resolve()
        path.relative_to(root)
        return path
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def publication_ledger(root, profile):
    """Resolve the vault's optional, explicitly configured publication tables."""
    selected = profile.get("workbench", {}).get("publication_ledger")
    return _rpm_vault_path(_rpm_Path(root).resolve(), selected)


def publication_table(ledger, filename):
    if ledger is None:
        return None
    path = _rpm_vault_path(ledger, filename)
    return path if path is not None and path.is_file() else None


def _rpm_body_path(root, item):
    try:
        path = _rpm_Path(_rpm_get(item, "path"))
        return _rpm_vault_path(root, path) if path.is_absolute() else None
    except (TypeError, ValueError):
        return None


def _rpm_json_read(path):
    try:
        with path.open(encoding="utf-8-sig") as stream:
            return _rpm_json.load(stream)
    except (OSError, ValueError):
        return None


def _rpm_stat(path):
    try:
        st = path.stat()
        return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
    except OSError:
        return None


def _rpm_frontmatter_scalar(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            value, end = _rpm_json.JSONDecoder().raw_decode(raw)
        except ValueError:
            return ""
        tail = raw[end:].strip()
        return value if not tail or tail.startswith("#") else ""
    if raw.startswith("'"):
        match = _rpm_re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", raw)
        return match[1].replace("''", "'") if match else ""
    raw = _rpm_re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
    if raw.casefold() in {"null", "~"} or raw[:1] in {"[", "{", "|", ">", "&", "*", "!", "#"}:
        return ""
    return raw


def _rpm_index_record(root, path):
    """读取约定的三个顶层标量，不解析正文、YAML 别名或标题。"""
    fields = {}
    try:
        with path.open(encoding="utf-8-sig") as stream:
            if stream.readline(4096).strip() != "---":
                return ["", "", ""]
            for _ in range(256):
                line = stream.readline(16384)
                if not line or len(line) == 16384:
                    return ["", "", ""]
                if line.strip() in {"---", "..."}:
                    break
                match = _rpm_re.match(r"^(canonical_body|asset_id|work_id):\s*(.*)$", line)
                if match:
                    key = match[1]
                    if key in fields:
                        return ["", "", ""]
                    fields[key] = _rpm_frontmatter_scalar(match[2])
            else:
                return ["", "", ""]
    except (OSError, UnicodeError):
        return ["", "", ""]
    canonical = _rpm_vault_path(root, fields.get("canonical_body"))
    return [
        str(canonical) if canonical is not None else "",
        fields.get("asset_id", ""),
        fields.get("work_id", ""),
    ]


def _rpm_cache_path(root):
    base = _rpm_os.environ.get("XDG_CACHE_HOME")
    base = _rpm_Path(base) if base and _rpm_Path(base).is_absolute() else _rpm_Path.home() / ".cache"
    key = _rpm_hashlib.sha256(_rpm_os.fsencode(root)).hexdigest()
    return base / "reading-info-published-v1" / (key + ".json")


def _rpm_cache_write(path, payload):
    temporary = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with _rpm_tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = _rpm_Path(stream.name)
            _rpm_json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
        _rpm_os.replace(temporary, path)
        temporary = None
    except OSError:
        pass
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _rpm_index_catalog(root):
    # 只缓存索引派生数据，不缓存快照或台账。索引增删/原子替换立即
    # 刷新；其他记录的原地编辑最多延迟一个刷新周期发现。刷新只打开
    # 指纹变了的文件。实际用于归因的候选索引始终重读验证。
    folder = root / _RPM_READING / "作品索引"
    stamp = _rpm_stat(folder)
    if stamp is None:
        return folder, {}
    try:
        cache_path = _rpm_cache_path(root)
    except (OSError, RuntimeError):
        cache_path = None
    cache = _rpm_json_read(cache_path) if cache_path is not None else None
    cache = cache if isinstance(cache, dict) else {}
    previous = cache.get("files")
    previous = previous if isinstance(previous, dict) else {}
    checked = cache.get("checked")
    now = _rpm_time.time()
    if (
        cache.get("directory") == stamp
        and type(checked) in (int, float)
        and 0 <= now - checked < _RPM_INDEX_REFRESH_SECONDS
    ):
        return folder, previous

    current = {}
    try:
        for path in folder.iterdir():
            if path.name.startswith(".") or not path.is_file():
                continue
            if _rpm_vault_path(root, path) is None:
                continue
            fingerprint = _rpm_stat(path)
            if fingerprint is None:
                continue
            old = previous.get(path.name)
            if isinstance(old, list) and len(old) == 4 and old[0] == fingerprint:
                current[path.name] = old
            else:
                current[path.name] = [fingerprint, *_rpm_index_record(root, path)]
    except OSError:
        return folder, {}
    if cache_path is not None and _rpm_stat(folder) == stamp:
        _rpm_cache_write(cache_path, {"directory": stamp, "checked": now, "files": current})
    return folder, current


def _rpm_row_refs(row):
    typed = _rpm_defaultdict(set)
    bare = set()

    def collect(value, allow_bare):
        if isinstance(value, _rpm_Mapping):
            for key, role in _RPM_ID_FIELDS.items():
                identifier = _rpm_id(value.get(key))
                if identifier:
                    typed[role].add(identifier)
        elif isinstance(value, (tuple, list, set, frozenset)):
            for entry in value:
                collect(entry, allow_bare)
        else:
            identifier = _rpm_id(value)
            if not identifier:
                return
            namespace, sep, suffix = identifier.partition(":")
            if sep and namespace in _RPM_ID_FIELDS and suffix.strip():
                typed[_RPM_ID_FIELDS[namespace]].add(suffix.strip())
            elif _RPM_ASSET_ID.fullmatch(identifier):
                typed["asset"].add(identifier)
            elif allow_bare:
                bare.add(identifier)

    collect({key: _rpm_get(row, key) for key in _RPM_ID_FIELDS}, False)
    collect(_rpm_get(row, "source_id"), True)
    collect(_rpm_get(row, "related_ids"), True)
    # aliases 可能是标题；仅接受明确带命名空间的 ID 或约定的 ASR ID。
    collect(_rpm_get(row, "aliases"), False)
    return typed, bare


def _rpm_index_matches(root, body, typed, bare):
    folder, catalog = _rpm_index_catalog(root)
    token_ids = bare | typed["asset"]
    candidates = set()
    for name, entry in catalog.items():
        if not isinstance(entry, list) or len(entry) != 4 or _rpm_Path(name).name != name:
            continue
        if entry[1] == str(body) or entry[2] in token_ids or _rpm_Path(name).stem in token_ids:
            candidates.add(folder / name)
    for identifier in token_ids:
        if _rpm_re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", identifier):
            for suffix in (".md", ".markdown", ""):
                path = folder / (identifier + suffix)
                if path.is_file():
                    candidates.add(path)

    paths, assets, works, foreign_assets = set(), set(), set(), set()
    for path in sorted(candidates):
        if _rpm_vault_path(root, path) is None:
            continue
        canonical, asset, work = _rpm_index_record(root, path)
        if canonical != str(body):
            if canonical and asset:
                foreign_assets.add(asset)
            continue
        paths.add(path)
        if asset:
            assets.add(asset)
        if work:
            works.add(work)
    return paths, assets, works, foreign_assets


def _rpm_review(root):
    pointer_path = root / _RPM_READING / "当前复盘.json"
    pointer = _rpm_json_read(pointer_path)
    pointer_keys = (
        "snapshot_path", "snapshot_file", "snapshot", "current_snapshot",
        "review_path", "path", "file",
    )

    def targets(value, depth=0):
        if isinstance(value, str):
            path = _rpm_vault_path(root, value)
            return {path} if path is not None else set()
        if isinstance(value, dict) and depth < 2:
            result = set()
            for key in pointer_keys:
                result.update(targets(value.get(key), depth + 1))
            return result
        return set()

    paths = targets(pointer) - {pointer_path}
    snapshot_path = next(iter(paths)) if len(paths) == 1 else None
    data = _rpm_json_read(snapshot_path) if snapshot_path is not None else (
        pointer if not paths else None
    )
    if not isinstance(data, dict):
        return pointer_path, snapshot_path, (), ""
    review = data.get("review")
    review = review if isinstance(review, dict) else {}
    rows = data.get("rows", review.get("rows"))
    captured = (
        _rpm_id(review.get("captured_at")) or _rpm_id(data.get("captured_at"))
        or _rpm_id(review.get("date")) or _rpm_id(data.get("date"))
    )
    return pointer_path, snapshot_path, rows if isinstance(rows, list) else (), captured


def _rpm_csv_rows(path):
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(_rpm_csv.DictReader(stream))
    except (OSError, UnicodeError, _rpm_csv.Error):
        return []


def _rpm_post_groups(ledger, review_rows):
    # publication_id 只连接 publication_id。当前视频号复盘的
    # object_id/legacy_object_id 用作该平台的精确帖子别名。
    entries = []
    platforms_by_publication = _rpm_defaultdict(set)
    for kind, filename in _RPM_TABLES:
        table = publication_table(ledger, filename)
        if table is None:
            continue
        for record in _rpm_csv_rows(table):
            platform = _rpm_platform(record.get("platform"))
            publication = _rpm_id(record.get("publication_id"))
            post = _rpm_id(record.get("platform_post_id"))
            if platform and publication:
                platforms_by_publication[publication].add(platform)
            if publication or post:
                entries.append((kind, record, platform, publication, post, ""))
    for record in review_rows:
        if not isinstance(record, dict):
            continue
        if _rpm_platform(record.get("platform")) not in {"", "视频号"}:
            continue
        post = _rpm_id(record.get("object_id"))
        legacy = _rpm_id(record.get("legacy_object_id"))
        if post or legacy:
            entries.append(("review", record, "视频号", "", post, legacy))

    parent = {}
    keyed_entries = []

    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for kind, record, platform, publication, post, legacy in entries:
        if not platform:
            possible = platforms_by_publication.get(publication, ())
            if len(possible) != 1:
                continue
            platform = next(iter(possible))
        keys = [
            (platform, namespace, identifier)
            for namespace, identifier in (
                ("publication", publication), ("post", post), ("post", legacy)
            )
            if identifier
        ]
        anchor = find(keys[0])
        for key in keys[1:]:
            parent[find(key)] = anchor
        keyed_entries.append((keys[0], (kind, record, publication, post, legacy)))

    groups = _rpm_defaultdict(list)
    for key, entry in keyed_entries:
        groups[find(key)].append(entry)
    return [(key[0], records) for key, records in groups.items()]


def _rpm_claims(root, body, records):
    assets, works, publications, review_ids = set(), set(), set(), set()
    ledger_posts, current_review_ids, legacy_review_ids = set(), set(), set()
    path_hit = False
    for kind, record, publication, post, legacy in records:
        asset = _rpm_id(record.get("asset_id"))
        work = _rpm_id(record.get("work_id"))
        if asset:
            assets.add(asset)
        if work:
            works.add(work)
        if publication:
            publications.add(publication)
        if kind == "review":
            if post:
                review_ids.add(post)
                current_review_ids.add(post)
            if legacy:
                review_ids.add(legacy)
                legacy_review_ids.add(legacy)
            path_fields = ("文稿文件", "校订稿")
        else:
            if post:
                ledger_posts.add(post)
            path_fields = ("transcript_path",) if kind == "performance" else ()
        if not path_hit:
            path_hit = any(_rpm_vault_path(root, record.get(field)) == body for field in path_fields)

    # 两个不同的台账平台帖 ID 不因冲突的 publication_id/历史别名而强行合并。
    # 当前 object_id 优先于 legacy；若新 ID 曾把旧 ID 列为 legacy，则选新 ID。
    review_heads = current_review_ids - legacy_review_ids
    post_name = (
        next(iter(ledger_posts)) if len(ledger_posts) == 1 else
        min(review_heads or current_review_ids or legacy_review_ids, default="")
    )
    return {
        "asset": assets,
        "work": works,
        "publication": publications,
        "review_object": review_ids,
        "path_hit": path_hit,
        "post": post_name,
        "valid": len(works) <= 1 and len(ledger_posts) <= 1,
    }


def _rpm_time_key(text):
    if not text:
        return (0, _rpm_dt.datetime.min, 0)
    try:
        dt = _rpm_dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(_rpm_dt.timezone.utc).replace(tzinfo=None)
        # 无时区的台账日期按记录的墙上时间排序，不使用运行机器的时区。
        return (1, dt, int(len(text) > 10))
    except (ValueError, OverflowError):
        return (0, _rpm_dt.datetime.min, 0)


def _rpm_metric_value(value):
    if isinstance(value, str):
        value = value.strip()
        if value.casefold() not in {"", "-", "--", "—", "n/a", "na", "null", "none", "nan"}:
            return value
    elif type(value) is int or (type(value) is float and _rpm_math.isfinite(value)):
        return value
    return None


def _rpm_latest(records, review_captured):
    latest = {}
    conflicts = set()
    for kind, record, _, _, _ in records:
        if kind == "publication":
            continue
        product = ""
        if kind == "conversion":
            product = _rpm_id(record.get("product_name"))
            start = _rpm_id(record.get("window_start"))
            end = _rpm_id(record.get("window_end"))
            rank = (_rpm_time_key(end), _rpm_time_key(start))
            if start and end:
                date_label = "窗口 " + start + " 至 " + end
            elif start:
                date_label = "窗口起 " + start
            elif end:
                date_label = "窗口止 " + end
            else:
                date_label = "窗口未记录"
        else:
            captured = _rpm_id(record.get("captured_at"))
            if not captured and kind == "review":
                captured = review_captured
            # 日期优先；同一采集时间才按来源优先级消解跨表重复。
            priority = {"review": 0, "performance": 1, "retention": 2}[kind]
            rank = (_rpm_time_key(captured), priority)
            date_label = "采集 " + captured if captured else "采集日期未记录"

        for field, label in _RPM_METRICS[kind].items():
            value = _rpm_metric_value(record.get(field))
            if value is None:
                continue
            key = (kind == "conversion", label, product)
            old = latest.get(key)
            if old is None or rank > old[0]:
                latest[key] = (rank, value, date_label)
                conflicts.discard(key)
            elif rank == old[0] and str(value) != str(old[1]):
                # 同一来源、同一时间而数值矛盾时，不能用文件行序猜哪个正确。
                conflicts.add(key)
    return [(key, latest[key][1], latest[key][2]) for key in sorted(latest) if key not in conflicts]


def published_metrics(root, item, row, *, profile=None):
    """返回可合入既有前端指标列表的 [{platform, label, value}]，不调用模型。"""
    root = _rpm_Path(root).resolve()
    body = _rpm_body_path(root, item)
    if body is None:
        return []

    typed, bare = _rpm_row_refs(row)
    _, indexed_assets, indexed_works, foreign_assets = _rpm_index_matches(root, body, typed, bare)
    if len(indexed_works) > 1:
        return []
    _, _, review_rows, review_captured = _rpm_review(root)
    groups = [
        (platform, records, _rpm_claims(root, body, records))
        for platform, records in _rpm_post_groups(publication_ledger(root, profile or {}), review_rows)
    ]

    # 未标注类型的行 ID 只在数据中恰好对应一种 ID 命名空间时使用。
    roles_by_id = _rpm_defaultdict(set)
    groups_by_ref = _rpm_defaultdict(set)
    for group_number, (_, _, claims) in enumerate(groups):
        for role in ("asset", "work", "publication", "review_object"):
            for identifier in claims[role]:
                roles_by_id[identifier].add(role)
                groups_by_ref[role, identifier].add(group_number)
    for identifier in indexed_assets | foreign_assets:
        roles_by_id[identifier].add("asset")
    for identifier in indexed_works:
        roles_by_id[identifier].add("work")
    for identifier in bare:
        roles = roles_by_id[identifier]
        if len(roles) == 1:
            typed[next(iter(roles))].add(identifier)

    # canonical_body 的证据优先于行 ID；已知指向其他正文的资产
    # 不能单独为当前正文建立归因。
    assets = (indexed_assets or typed["asset"]) - foreign_assets
    inferred_works = set()
    for _, _, claims in groups:
        if claims["valid"] and (claims["path_hit"] or claims["asset"] & assets):
            inferred_works.update(claims["work"])
    work_candidates = indexed_works or inferred_works or typed["work"]
    work = next(iter(work_candidates)) if len(work_candidates) == 1 else ""

    output = []
    for number, (platform, records, claims) in enumerate(groups):
        if not claims["valid"] or (work and claims["work"] and work not in claims["work"]):
            continue
        asset_hit = bool(claims["asset"] & assets)
        work_hit = bool(work and work in claims["work"])
        post_hit = any(
            groups_by_ref[role, identifier] == {number}
            for role in ("publication", "review_object")
            for identifier in typed[role] & claims[role]
        )
        if not (claims["path_hit"] or asset_hit or work_hit or post_hit):
            continue
        if not work_hit:
            if claims["asset"] & foreign_assets:
                continue
            if assets and claims["asset"] - assets and not claims["path_hit"]:
                continue
            if len(work_candidates) > 1 and not (claims["path_hit"] or asset_hit):
                continue

        if claims["post"]:
            post_label = "帖 " + claims["post"]
        else:
            post_label = "发布 " + "/".join(sorted(claims["publication"]))
        for (_, label, product), value, date_label in _rpm_latest(records, review_captured):
            parts = [label]
            if product:
                parts.append(product)
            parts.extend((post_label, date_label))
            output.append({"platform": platform, "label": " · ".join(parts), "value": value})

    return sorted(output, key=lambda metric: (metric["platform"], metric["label"]))


def watch_reading_files(root, item, row, *, profile=None):
    """返回当前作品依赖的现存原文件，不包含索引派生缓存。"""
    root = _rpm_Path(root).resolve()
    body = _rpm_body_path(root, item)
    if body is None:
        return []
    typed, bare = _rpm_row_refs(row)
    indexes, _, _, _ = _rpm_index_matches(root, body, typed, bare)
    pointer, snapshot, _, _ = _rpm_review(root)
    paths = [body, *sorted(indexes), pointer, snapshot]
    ledger = publication_ledger(root, profile or {})
    paths.extend(publication_table(ledger, filename) for _, filename in _RPM_TABLES)
    return list(dict.fromkeys(path for path in paths if path is not None and path.is_file()))
