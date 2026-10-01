"""防汛值守领域规则：预警级别阶梯、升级发布、联动通知/排水任务/道路风险面。

链路（一次升级按顺序经过四层，全部在同一事务内提交）：
    预警记录（防汛档案） -> 通知栏 -> 排水任务 -> 道路风险面

约束：
- 级别只能沿阶梯（蓝→黄→橙→红）推进相邻一级，重复发布同一级不产生第二条事件；
- 每个预警事件一把锁 + version 版本位，并发值守只允许一版成功；
- 指挥部最新命令覆盖自动监测建议；每次命令都在历史阶梯留档；
- 通知与任务同事务提交，任一步失败整体回滚，维持此前级别；
- 存量跳级记录在启动时迁回相邻节点。
"""
from __future__ import annotations

import copy
import hashlib
import threading
from datetime import datetime
from typing import Any

from app.store import store

# 预警级别阶梯：下标即等级高低，相邻节点才能推进
LEVELS: list[str] = ["蓝色预警", "黄色预警", "橙色预警", "红色预警"]

# 各级别对应的排水任务状态（按下标对齐，避免“状态错位”）
DRAINAGE_TASK_STATUS: dict[str, str] = {
    "蓝色预警": "值守巡查",
    "黄色预警": "预抽排待命",
    "橙色预警": "强制抽排",
    "红色预警": "抢险抽排",
}

# 各级别对应的道路风险面：风险等级 + 管控状态
ROAD_RISK_LEVEL: dict[str, str] = {
    "蓝色预警": "低风险",
    "黄色预警": "中风险",
    "橙色预警": "高风险",
    "红色预警": "极高风险",
}
ROAD_RISK_CONTROL: dict[str, str] = {
    "蓝色预警": "正常通行",
    "黄色预警": "减速提示",
    "橙色预警": "交通管制",
    "红色预警": "道路封闭",
}

FLOOD_MODULE = "flood"
NOTICE_TABLE = "flood_notice"          # 通知栏：每个事件一行，按事件 upsert
COMMAND_TABLE = "flood_command"        # 历史阶梯：每次指挥部命令一行
TASK_TABLE = "flood_drainage_task"     # 排水任务：每个事件×影响路段一行
RISK_TABLE = "flood_road_risk"         # 道路风险面：每个事件×影响路段一行
MIGRATION_TABLE = "flood_migration"    # 存量跳级迁移留痕

ACTIVE_STATUSES = {"待响应", "响应中"}
SECTION_SPLIT_CHARS = "、,，;；\n"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def rank(level: str | None) -> int:
    """级别在阶梯上的位置；未知级别视为阶梯之外（-1）。"""
    try:
        return LEVELS.index(level or "")
    except ValueError:
        return -1


def split_sections(value: Any) -> list[str]:
    """影响路段字段可能是列表，也可能是顿号拼接的字符串，统一拆成清单。"""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    for char in SECTION_SPLIT_CHARS:
        text = text.replace(char, "|")
    return [part.strip() for part in text.split("|") if part.strip()]


class Transaction:
    """小型事务：对触及到的行做快照，异常时恢复旧值、移除新增行。

    内存仓库没有数据库事务，这里显式记录“已有行的深拷贝”和“新增行对象”，
    保证通知与任务等多张表要么一起生效、要么一起回到提交前。
    """

    def __init__(self) -> None:
        self._touched: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self._appended: list[tuple[str, dict[str, Any]]] = []

    def touch(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        self._touched.append((table, row, copy.deepcopy(row)))
        return row

    def append(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        store.rows(table).append(row)
        self._appended.append((table, row))
        return row

    def rollback(self) -> None:
        for table, row, snapshot in self._touched:
            row.clear()
            row.update(snapshot)
        for table, row in self._appended:
            try:
                store.rows(table).remove(row)
            except ValueError:
                pass


class FloodWatchService:
    """防汛值守：管理升级链路、并发版本与存量迁移。"""

    def __init__(self) -> None:
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._bootstrapped = False

    # ---- 基础查询 -------------------------------------------------------

    def _lock_for(self, event_id: int) -> threading.Lock:
        with self._locks_guard:
            if event_id not in self._locks:
                self._locks[event_id] = threading.Lock()
            return self._locks[event_id]

    @staticmethod
    def effective_level(event: dict[str, Any]) -> str:
        """当前生效级别：有指挥部命令时命令覆盖自动监测，否则取自动监测建议。"""
        command_level = event.get("command_level")
        if rank(command_level) >= 0:
            return str(command_level)
        auto = event.get("auto_level")
        return auto if rank(auto) >= 0 else LEVELS[0]

    def list_notifications(self) -> list[dict[str, Any]]:
        """通知栏：只挂在未结束的事件上，按级别从高到低排列。"""
        active_ids = {
            int(row["id"])
            for row in store.rows(FLOOD_MODULE)
            if row.get("status") in ACTIVE_STATUSES
        }
        notices = [
            row for row in store.rows(NOTICE_TABLE)
            if int(row.get("事件id", 0)) in active_ids
        ]
        notices.sort(key=lambda row: rank(row.get("级别")), reverse=True)
        return notices

    def list_drainage_tasks(self, event_id: int | None = None) -> list[dict[str, Any]]:
        rows = store.rows(TASK_TABLE)
        if event_id is not None:
            rows = [row for row in rows if int(row.get("事件id", 0)) == event_id]
        return rows

    def list_commands(self, event_id: int) -> list[dict[str, Any]]:
        rows = [
            row for row in store.rows(COMMAND_TABLE)
            if int(row.get("事件id", 0)) == event_id
        ]
        rows.sort(key=lambda row: int(row.get("序次", 0)))
        return rows

    def road_risk_workbench(self) -> dict[str, Any]:
        """道路风险工作台：按路段汇总风险面，取该路段上的最高风险。"""
        sections: dict[str, dict[str, Any]] = {}
        for row in store.rows(RISK_TABLE):
            name = str(row.get("影响路段", ""))
            current = sections.get(name)
            if current is None or rank(str(row.get("预警级别", ""))) > rank(str(current.get("预警级别", ""))):
                sections[name] = copy.deepcopy(row)
                current = sections[name]
            current.setdefault("关联事件", [])
            current["关联事件"].append({
                "事件id": row.get("事件id"),
                "记录编号": row.get("记录编号"),
                "预警级别": row.get("预警级别"),
            })
        items = sorted(
            sections.values(),
            key=lambda item: rank(str(item.get("预警级别", ""))),
            reverse=True,
        )
        return {
            "levels": LEVELS,
            "total": len(items),
            "items": items,
            "notices": self.list_notifications(),
        }

    # ---- 影响路段核对 ---------------------------------------------------

    def check_affected_sections(self, event_id: int) -> tuple[dict[str, Any] | None, str]:
        """第二步：核对影响路段。

        把防汛记录里的影响路段，与排水设施台账、管养路段台账交叉核对，
        返回核对凭证 check_token；发布升级时必须回传该凭证，确保“先核对再发布”。
        """
        event = store.find(FLOOD_MODULE, event_id)
        if event is None:
            return None, f"防汛记录 {event_id} 不存在或已归档"
        if event.get("status") not in ACTIVE_STATUSES:
            return None, f"预警事件当前为「{event.get('status')}」，无需再核对影响路段"
        names = split_sections(event.get("影响路段"))
        if not names:
            return None, "该预警事件尚未登记影响路段，无法核对"
        sections: list[dict[str, Any]] = []
        for name in names:
            facilities = [
                row for row in store.rows("drainage")
                if name in str(row.get("所属路段", ""))
            ]
            road_rows = [
                row for row in store.rows("road_section")
                if name in str(row.get("路段名称", "")) or name in str(row.get("起止桩号", ""))
            ]
            task = next(
                (row for row in store.rows(TASK_TABLE)
                 if int(row.get("事件id", 0)) == event_id and row.get("影响路段") == name),
                None,
            )
            risk = next(
                (row for row in store.rows(RISK_TABLE)
                 if int(row.get("事件id", 0)) == event_id and row.get("影响路段") == name),
                None,
            )
            sections.append({
                "影响路段": name,
                "排水设施": [
                    {"设施编号": row.get("设施编号"), "设施状态": row.get("status")}
                    for row in facilities
                ],
                "管养路段": [
                    {"路段编号": row.get("路段编号"), "路段状态": row.get("status")}
                    for row in road_rows
                ],
                "当前排水任务": task.get("任务状态") if task else None,
                "当前风险面": risk.get("风险等级") if risk else None,
                "台账齐套": bool(facilities and road_rows),
            })
        payload = {
            "事件id": event_id,
            "记录编号": event.get("记录编号"),
            "version": int(event.get("version", 1)),
            "sections": sections,
            "checked_at": now_text(),
        }
        payload["check_token"] = self._make_check_token(event, names)
        return payload, ""

    @staticmethod
    def _make_check_token(event: dict[str, Any], names: list[str]) -> str:
        joined = "|".join(names)
        digest = hashlib.md5(f"{event['id']}:{event.get('version', 1)}:{joined}".encode("utf-8")).hexdigest()[:10]
        return f"chk-{event['id']}-{event.get('version', 1)}-{len(names)}-{digest}"

    # ---- 自动监测 -------------------------------------------------------

    def report_monitoring(
        self, event_id: int, suggested_level: str
    ) -> tuple[dict[str, Any] | None, str]:
        """自动监测上报建议级别；只更新建议值，指挥部命令在时不改变生效级别。"""
        event = store.find(FLOOD_MODULE, event_id)
        if event is None:
            return None, f"防汛记录 {event_id} 不存在或已归档"
        if rank(suggested_level) < 0:
            return None, f"建议级别「{suggested_level}」不在阶梯 {('、'.join(LEVELS))} 内"
        with self._lock_for(event_id):
            event["auto_level"] = suggested_level
            event["监测上报时间"] = now_text()
        return {
            "事件id": event_id,
            "自动监测建议": suggested_level,
            "指挥部命令": event.get("command_level"),
            "生效级别": self.effective_level(event),
            "被命令覆盖": rank(event.get("command_level")) >= 0,
        }, ""

    # ---- 升级发布（核心链路）--------------------------------------------

    def escalate(
        self,
        event_id: int,
        target_level: str,
        *,
        operator: str = "防汛值班员",
        check_token: str = "",
        expected_version: int | None = None,
        remark: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """发布升级：定位事件 -> 已核对路段 -> 发布，四层在同一事务内提交。"""
        if rank(target_level) < 0:
            return None, f"目标级别「{target_level}」不在阶梯 {('、'.join(LEVELS))} 内"

        with self._lock_for(event_id):
            event = store.find(FLOOD_MODULE, event_id)
            if event is None:
                return None, f"防汛记录 {event_id} 不存在或已归档"
            if event.get("status") not in ACTIVE_STATUSES:
                return None, "预警事件已结束，不能再发布升级"

            current = self.effective_level(event)
            current_rank = rank(current)
            target_rank = rank(target_level)

            # 并发值守：version 不一致说明已有另一版先提交（先于其它判断，给出并发口径）
            current_version = int(event.get("version", 1))
            if expected_version is not None and expected_version != current_version:
                return None, "已有其他值守人员推进了一版，请刷新最新状态后再操作"

            # 幂等：同一级重复点击直接拦下，不再产生第二条命令/通知/任务
            if target_rank == current_rank:
                return None, f"{target_level} 已发布，请勿重复提交"
            if target_rank < current_rank:
                return None, f"升级不能回退级别（当前 {current}），降级需走解除响应流程"
            if target_rank != current_rank + 1:
                return None, f"只能升级到相邻节点（{current} 的上一级为 {LEVELS[current_rank + 1]}），不允许跳级发布"

            names = split_sections(event.get("影响路段"))
            if not names:
                return None, "影响路段为空，无法联动排水任务与道路风险面"
            if check_token != self._make_check_token(event, names):
                return None, "请先核对影响路段，凭核对凭证再发布升级"

            tx = Transaction()
            try:
                self._apply_escalation(tx, event, names, target_level, operator, remark)
            except Exception as exc:  # 任何一步失败都回滚，维持此前级别
                tx.rollback()
                return None, f"升级发布失败已回滚，维持 {current}：{exc}"

            return {
                "event": copy.deepcopy(event),
                "notice": copy.deepcopy(self._find_notice(event_id)),
                "tasks": copy.deepcopy(self.list_drainage_tasks(event_id)),
                "risks": copy.deepcopy(
                    [row for row in store.rows(RISK_TABLE) if int(row.get("事件id", 0)) == event_id]
                ),
            }, f"预警已升级至{target_level}，通知、排水任务与道路风险面已同步"

    def _apply_escalation(
        self,
        tx: Transaction,
        event: dict[str, Any],
        names: list[str],
        target_level: str,
        operator: str,
        remark: str,
    ) -> None:
        event_id = int(event["id"])
        issued_at = now_text()

        # 第 1 层：防汛档案 + 历史阶梯留档
        tx.touch(FLOOD_MODULE, event)
        seq = len(self.list_commands(event_id)) + 1
        event["预警级别"] = target_level
        event["command_level"] = target_level
        event["来源"] = "指挥部命令"
        event["version"] = int(event.get("version", 1)) + 1
        event["最新命令时间"] = issued_at
        event["防汛状态"] = event.get("status")
        if event.get("status") == "待响应":
            event["status"] = "响应中"
            event["pending"] = True
        tx.append(COMMAND_TABLE, {
            "id": self._next_id(COMMAND_TABLE),
            "事件id": event_id,
            "记录编号": event.get("记录编号"),
            "序次": seq,
            "级别": target_level,
            "来源": "指挥部命令",
            "发布人": operator,
            "命令说明": remark or f"升级至{target_level}",
            "发布时间": issued_at,
        })

        # 第 2 层：通知栏（按事件 upsert，重复点击也只有一条）
        notice = self._find_notice(event_id)
        notice_payload = {
            "事件id": event_id,
            "记录编号": event.get("记录编号"),
            "级别": target_level,
            "标题": f"{event.get('记录编号')} {target_level}生效中",
            "影响路段": names,
            "更新时间": issued_at,
        }
        if notice is None:
            notice = {"id": self._next_id(NOTICE_TABLE), **notice_payload}
            tx.append(NOTICE_TABLE, notice)
        else:
            tx.touch(NOTICE_TABLE, notice)
            notice.update(notice_payload)

        # 第 3 层：排水任务（事件 × 路段 upsert，状态按阶梯下标对齐）
        for name in names:
            task = self._find_task(event_id, name)
            task_payload = {
                "事件id": event_id,
                "记录编号": event.get("记录编号"),
                "影响路段": name,
                "预警级别": target_level,
                "任务状态": DRAINAGE_TASK_STATUS[target_level],
                "更新时间": issued_at,
            }
            if task is None:
                tx.append(TASK_TABLE, {"id": self._next_id(TASK_TABLE), **task_payload})
            else:
                tx.touch(TASK_TABLE, task)
                task.update(task_payload)

        # 第 4 层：道路风险面（事件 × 路段 upsert，等级/管控双对齐）
        for name in names:
            risk = self._find_risk(event_id, name)
            risk_payload = {
                "事件id": event_id,
                "记录编号": event.get("记录编号"),
                "影响路段": name,
                "预警级别": target_level,
                "风险等级": ROAD_RISK_LEVEL[target_level],
                "管控状态": ROAD_RISK_CONTROL[target_level],
                "更新时间": issued_at,
            }
            if risk is None:
                tx.append(RISK_TABLE, {"id": self._next_id(RISK_TABLE), **risk_payload})
            else:
                tx.touch(RISK_TABLE, risk)
                risk.update(risk_payload)

    # ---- 存量迁移 / 初始化 ----------------------------------------------

    def bootstrap(self) -> None:
        """启动时执行一次：迁移存量跳级记录，并为在警事件补齐联动数据。"""
        if self._bootstrapped:
            return
        self._bootstrapped = True
        self._migrate_skip_levels()
        for event in store.rows(FLOOD_MODULE):
            if event.get("status") in ACTIVE_STATUSES:
                self.ensure_aligned(event)

    def _migrate_skip_levels(self) -> None:
        """存量跳级记录迁回相邻节点。

        口径：以历史阶梯里最后一次命令（无命令则以蓝色为基准）为前一节点，
        当前级别若高出相邻节点以上，就迁回到“前一节点的上一级”，并留痕。
        """
        for event in store.rows(FLOOD_MODULE):
            level = event.get("预警级别")
            if rank(level) < 0:
                continue
            commands = self.list_commands(int(event["id"]))
            last_command = commands[-1]["级别"] if commands else LEVELS[0]
            expected_adjacent_rank = rank(last_command) + 1
            if rank(level) > expected_adjacent_rank:
                target = LEVELS[expected_adjacent_rank]
                note = {
                    "id": self._next_id(MIGRATION_TABLE),
                    "事件id": int(event["id"]),
                    "记录编号": event.get("记录编号"),
                    "原级别": level,
                    "迁回级别": target,
                    "原因": "存量记录缺少中间命令阶梯，迁回相邻节点",
                    "迁移时间": now_text(),
                }
                store.rows(MIGRATION_TABLE).append(note)
                event["预警级别"] = target
                if rank(event.get("command_level")) > expected_adjacent_rank:
                    event["command_level"] = target
                if rank(event.get("auto_level")) > expected_adjacent_rank:
                    event["auto_level"] = target
                event["迁移说明"] = f"原{level}跳级，已迁回相邻节点{target}"

    def ensure_aligned(self, event: dict[str, Any]) -> None:
        """为在警事件补齐与当前级别一致的通知/任务/风险面（启动对齐用）。"""
        if event.get("status") not in ACTIVE_STATUSES:
            return
        event_id = int(event["id"])
        names = split_sections(event.get("影响路段"))
        if not names:
            return
        level = self.effective_level(event)
        if not self._find_notice(event_id):
            store.rows(NOTICE_TABLE).append({
                "id": self._next_id(NOTICE_TABLE),
                "事件id": event_id,
                "记录编号": event.get("记录编号"),
                "级别": level,
                "标题": f"{event.get('记录编号')} {level}生效中",
                "影响路段": names,
                "更新时间": now_text(),
            })
        for name in names:
            if not self._find_task(event_id, name):
                store.rows(TASK_TABLE).append({
                    "id": self._next_id(TASK_TABLE),
                    "事件id": event_id,
                    "记录编号": event.get("记录编号"),
                    "影响路段": name,
                    "预警级别": level,
                    "任务状态": DRAINAGE_TASK_STATUS[level],
                    "更新时间": now_text(),
                })
            if not self._find_risk(event_id, name):
                store.rows(RISK_TABLE).append({
                    "id": self._next_id(RISK_TABLE),
                    "事件id": event_id,
                    "记录编号": event.get("记录编号"),
                    "影响路段": name,
                    "预警级别": level,
                    "风险等级": ROAD_RISK_LEVEL[level],
                    "管控状态": ROAD_RISK_CONTROL[level],
                    "更新时间": now_text(),
                })

    def register_event(self, event: dict[str, Any]) -> None:
        """新登记防汛记录时，按初始级别建立基线联动数据。"""
        self.ensure_aligned(event)

    # ---- 内部工具 -------------------------------------------------------

    @staticmethod
    def _next_id(table: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1

    @staticmethod
    def _find_notice(event_id: int) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(NOTICE_TABLE) if int(row.get("事件id", 0)) == event_id),
            None,
        )

    @staticmethod
    def _find_task(event_id: int, section: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(TASK_TABLE)
             if int(row.get("事件id", 0)) == event_id and row.get("影响路段") == section),
            None,
        )

    @staticmethod
    def _find_risk(event_id: int, section: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(RISK_TABLE)
             if int(row.get("事件id", 0)) == event_id and row.get("影响路段") == section),
            None,
        )


watch_service = FloodWatchService()
