"""防汛预警升级领域规则：四级阶梯、命令覆盖监测、历史留档与影响面投影。

升级链路统一在这里收口，避免路由层各改一半：

    防汛档案(flood 记录)
        └─ 通知栏(按事件去重的生效预警)
        └─ 排水任务(drainage 行上的预警级别/任务状态)
        └─ 道路风险面(road_section 行上的风险等级/管控状态)

约束：
- 预警只能沿 LEVELS 逐档推进，每次指挥部命令只允许推进相邻一级；
- 指挥部最新命令覆盖自动监测级别；
- 每次命令在历史阶梯里留一档；
- 存量跳级记录（如蓝色直接跳到红色）启动时迁回相邻节点；
- 通知与任务在同一事务里提交，任一步失败整体回滚，维持此前级别。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

FLOOD = "flood"
ROAD = "road_section"
DRAINAGE = "drainage"
NOTICE = "flood_notice"

# Ⅳ(蓝) -> Ⅲ(黄) -> Ⅱ(橙) -> Ⅰ(红)，顺序即升级阶梯。
LEVELS: list[str] = ["蓝色预警", "黄色预警", "橙色预警", "红色预警"]
LEVEL_ORDERS: list[str] = ["Ⅳ级", "Ⅲ级", "Ⅱ级", "Ⅰ级"]

SOURCE_MONITOR = "自动监测"
SOURCE_COMMAND = "指挥部命令"
SOURCE_MIGRATION = "存量迁移"
MANUAL_SOURCES = (SOURCE_COMMAND, SOURCE_MIGRATION)

ENDED_STATUS = "已结束"

# 排水任务状态必须与预警档位对齐，避免“级别升了、任务还停在低档/状态错位”。
DRAINAGE_TASK_STATUS: dict[str, str] = {
    "蓝色预警": "待执行",
    "黄色预警": "执行中",
    "橙色预警": "执行中（加密布控）",
    "红色预警": "执行中（全员到岗）",
}
DRAINAGE_TASK_IDLE = "无排水任务"

# 道路风险面与预警档位对齐。
ROAD_RISK_STATUS: dict[str, str] = {
    "蓝色预警": "低风险·关注",
    "黄色预警": "中风险·管控",
    "橙色预警": "高风险·限行准备",
    "红色预警": "极高风险·封闭管控",
}
ROAD_RISK_IDLE = "常态通行"
RISK_IDLE_LEVEL = "无"


class FloodConflict(RuntimeError):
    """并发值守时版本已被推进，或同一条命令被重复提交。"""


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def level_index(level: str | None) -> int:
    try:
        return LEVELS.index(level or LEVELS[0])
    except ValueError:
        return 0


def next_level(level: str) -> str | None:
    idx = level_index(level)
    if idx >= len(LEVELS) - 1:
        return None
    return LEVELS[idx + 1]


def road_codes(entry: dict[str, Any]) -> list[str]:
    return [str(code) for code in entry.get("road_codes", []) if str(code).strip()]


def last_history(entry: dict[str, Any], source: str | None = None) -> dict[str, Any] | None:
    history = entry.get("history", [])
    if source is None:
        return history[-1] if history else None
    for item in reversed(history):
        if item.get("source") == source:
            return item
    return None


def effective_level(entry: dict[str, Any]) -> str:
    """生效级别：最新一条人工命令（含存量迁移动作）覆盖自动监测。"""
    for item in reversed(entry.get("history", [])):
        if item.get("source") in MANUAL_SOURCES:
            return str(item["level"])
    return str(entry.get("监测级别") or entry.get("预警级别") or LEVELS[0])


def append_history(
    entry: dict[str, Any],
    *,
    source: str,
    level: str,
    command_no: str = "",
    operator: str = "",
    note: str = "",
    roads: list[str] | None = None,
) -> dict[str, Any]:
    seq = int(entry.get("command_seq", 0)) + 1
    version = int(entry.get("version", 1))
    if source == SOURCE_COMMAND:
        version += 1
    item = {
        "seq": seq,
        "at": now_text(),
        "source": source,
        "command_no": command_no,
        "operator": operator,
        "level": level,
        "note": note,
        "roads": list(roads if roads is not None else road_codes(entry)),
        "version": version,
    }
    entry.setdefault("history", []).append(item)
    entry["command_seq"] = seq
    if source == SOURCE_COMMAND:
        entry["version"] = version
    return item


def _road_name_map(tables: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    return {str(r.get("路段编号", "")): str(r.get("路段名称", "")) for r in tables.get(ROAD, [])}


def _active_entries(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in tables.get(FLOOD, [])
        if entry.get("status") != ENDED_STATUS
    ]


def project_surfaces(tables: dict[str, list[dict[str, Any]]]) -> None:
    """依据全部生效防汛事件，重算排水任务与道路风险面。

    全量重算而非增量修补：升级时值班员可能调整影响路段，只有重算才能把
    已移出路段上残留的高等级标记清干净，杜绝“状态错位”。
    """
    roads = tables.setdefault(ROAD, [])
    drains = tables.setdefault(DRAINAGE, [])

    for road in roads:
        road["风险等级"] = RISK_IDLE_LEVEL
        road["风险面状态"] = ROAD_RISK_IDLE
        road["关联防汛记录"] = ""

    for drain in drains:
        drain["预警级别"] = ""
        drain["排水任务状态"] = DRAINAGE_TASK_IDLE
        drain["关联防汛记录"] = ""

    # 同一路段可能被多起事件覆盖，风险面取最高档；记录编号留最高档事件。
    road_top: dict[str, tuple[int, dict[str, Any]]] = {}
    for entry in _active_entries(tables):
        level = effective_level(entry)
        idx = level_index(level)
        for code in road_codes(entry):
            current = road_top.get(code)
            if current is None or idx > current[0]:
                road_top[code] = (idx, entry)

    name_map = _road_name_map(tables)
    for road in roads:
        code = str(road.get("路段编号", ""))
        top = road_top.get(code)
        if top is None:
            continue
        _, entry = top
        level = effective_level(entry)
        road["风险等级"] = level
        road["风险面状态"] = ROAD_RISK_STATUS[level]
        road["关联防汛记录"] = entry.get("记录编号", "")
        road["风险颜色序"] = level_index(level)

    for drain in drains:
        code = str(drain.get("所属路段", ""))
        top = road_top.get(code)
        if top is None:
            continue
        _, entry = top
        level = effective_level(entry)
        drain["预警级别"] = level
        drain["排水任务状态"] = DRAINAGE_TASK_STATUS[level]
        drain["关联防汛记录"] = entry.get("记录编号", "")

    _project_notices(tables, name_map)
    _refresh_flags(tables)


def _project_notices(
    tables: dict[str, list[dict[str, Any]]],
    name_map: dict[str, str],
) -> None:
    """通知栏按事件 upsert：一个预警事件始终只有一条，杜绝重复点击产生第二条。

    整表按事件 id 原地重建（沿用同一行 id 做 upsert 语义）：
    已结束/被降档撤销的事件会从通知栏撤下，活动事件取命令覆盖监测后的生效级别。
    """
    notices = tables.setdefault(NOTICE, [])
    by_id = {int(row.get("event_id")): row for row in notices}
    active = _active_entries(tables)
    active_ids = {int(entry.get("id", 0)) for entry in active}

    for row in list(notices):
        if int(row.get("event_id", -1)) not in active_ids:
            notices.remove(row)

    for entry in active:
        event_id = int(entry.get("id", 0))
        level = effective_level(entry)
        codes = road_codes(entry)
        payload = {
            "event_id": event_id,
            "记录编号": entry.get("记录编号", ""),
            "级别": level,
            "级别序": level_index(level),
            "标题": f"{entry.get('记录编号', '')} 生效{level}",
            "影响路段": "、".join(
                f"{code} {name_map.get(code, '')}".strip() for code in codes
            ),
            "状态": entry.get("status", ""),
            "updated_at": now_text(),
            "active": True,
        }
        existing = by_id.get(event_id)
        if existing is None:
            notices.append({"id": event_id, **payload})
        else:
            existing.update(payload)



def _refresh_flags(tables: dict[str, list[dict[str, Any]]]) -> None:
    for entry in tables.get(FLOOD, []):
        level = effective_level(entry)
        entry["预警级别"] = level
        entry["pending"] = entry.get("status") != ENDED_STATUS
        entry["abnormal"] = level_index(level) >= 2


def migrate_legacy(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    """存量跳级记录迁回相邻节点。

    沿历史阶梯逐档比对：某条指挥部命令相对上一档位跳了不止一级，
    就把生效级别拉回跳级点的相邻节点，并追加一档“存量迁移”留痕。
    """
    logs: list[str] = []
    for entry in tables.get(FLOOD, []):
        history = entry.setdefault("history", [])
        previous: str | None = None
        for item in history:
            if item.get("source") == SOURCE_COMMAND:
                if previous is not None:
                    gap = level_index(item.get("level")) - level_index(previous)
                    if gap > 1:
                        target = LEVELS[level_index(previous) + 1]
                        record_no = entry.get("记录编号", entry.get("id", "?"))
                        note = (
                            f"存量跳级记录迁回相邻节点：原命令 {previous}→{item.get('level')}，"
                            f"按逐档推进规则校正为 {target}"
                        )
                        append_history(
                            entry,
                            source=SOURCE_MIGRATION,
                            level=target,
                            command_no="",
                            operator="系统迁移",
                            note=note,
                        )
                        logs.append(f"{record_no}: {note}")
                        break  # 一条记录只处理首个跳级点，后续以迁移动作为准
                previous = str(item.get("level"))
            elif item.get("source") == SOURCE_MONITOR:
                previous = str(item.get("level"))
    return logs


def bootstrap(tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """仓库初始化时调用：先迁存量，再把生效级别投影到各影响面。"""
    logs = migrate_legacy(tables)
    for entry in tables.get(FLOOD, []):
        entry.setdefault("version", 1)
        entry.setdefault("command_seq", len(entry.get("history", [])))
        entry.setdefault("监测级别", effective_level(entry))
        entry["预警级别"] = effective_level(entry)
        entry.setdefault("updated_at", now_text())
    project_surfaces(tables)
    return {"migrated": logs}


def present_entry(entry: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """给前端的明细：内部 road_codes 之外补一份可读的影响路段文本。"""
    data = dict(entry)
    name_map = _road_name_map(tables)
    codes = road_codes(entry)
    data["road_codes"] = codes
    data["影响路段"] = "、".join(
        f"{code} {name_map.get(code, '')}".strip() for code in codes
    )
    data["影响路段明细"] = [{"code": code, "name": name_map.get(code, "")} for code in codes]
    data["历史阶梯"] = list(entry.get("history", []))
    manual = None
    for item in reversed(entry.get("history", [])):
        if item.get("source") in MANUAL_SOURCES:
            manual = item
            break
    data["生效来源"] = manual.get("source") if manual else SOURCE_MONITOR
    return data
