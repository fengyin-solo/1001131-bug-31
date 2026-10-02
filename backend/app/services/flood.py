"""防汛应急业务规则：四级预警升级、命令覆盖监测、影响面联动与事务提交。

升级发布是本模块唯一的写入主链路：
    定位预警事件 -> 核对影响路段 -> 发布升级
一次发布在同一个事务里依次落 防汛档案 / 通知栏 / 排水任务 / 道路风险面，
任何一步失败整体回滚，维持此前级别；version 乐观锁保证并发值守只推进一版，
command_no 幂等保证重复点击不会生成第二档命令、第二条通知。
"""
from __future__ import annotations

from typing import Any

from app import flood_domain as fd
from app.flood_domain import (
    DRAINAGE,
    ENDED_STATUS,
    FLOOD,
    ROAD,
    FloodConflict,
    SOURCE_COMMAND,
    SOURCE_MONITOR,
    effective_level,
    level_index,
    next_level,
    now_text,
    present_entry,
    project_surfaces,
    road_codes,
    append_history,
)
from app.store import store

MODULE = FLOOD
NOTICE_MODULE = "flood_notice"
REQUIRED_FIELDS = ["记录编号", "影响路段"]
STATUS_ORDER = ["待响应", "响应中", "已处置", "已结束"]
ACTION_RULES = {"启动响应": "响应中", "完成处置": "已处置", "结束响应": "已结束"}


class FloodService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        tables = store.tables()
        rows = list(tables.get(MODULE, []))
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = [present_entry(row, tables) for row in rows[start:start + size]]
        return page_rows, total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return present_entry(entry, store.tables())

    def get_history(self, entry_id: int) -> list[dict[str, Any]] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return list(entry.get("history", []))

    # ---------- 登记 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        roads_value = values.get("road_codes")
        if not roads_value and not missing:
            missing.append("影响路段")
        if missing:
            return None, missing
        codes = self._normalize_roads(roads_value)
        valid_codes = {str(row.get("路段编号", "")) for row in store.rows(ROAD)}
        invalid = [code for code in codes if code not in valid_codes]
        if invalid:
            return None, [f"影响路段 {('、'.join(invalid))} 不在管养路段台账内"]
        with store.transaction() as tables:
            rows = tables[MODULE]
            codes = self._normalize_roads(roads_value)
            entry: dict[str, Any] = {"id": store.next_id(MODULE)}
            entry["记录编号"] = str(values.get("记录编号") or "").strip()
            entry["status"] = STATUS_ORDER[0]
            entry["防汛状态"] = STATUS_ORDER[0]
            entry["积水深度"] = str(values.get("积水深度") or "")
            entry["应急措施"] = str(values.get("应急措施") or "")
            entry["投入人员"] = str(values.get("投入人员") or "")
            entry["恢复时间"] = ""
            entry["road_codes"] = codes
            entry["监测级别"] = fd.LEVELS[0]
            entry["预警级别"] = fd.LEVELS[0]
            entry["version"] = 1
            entry["command_seq"] = 0
            entry["history"] = []
            entry["updated_at"] = now_text()
            rows.append(entry)
            append_history(
                entry,
                source=SOURCE_MONITOR,
                level=fd.LEVELS[0],
                operator="自动监测",
                note="新登记防汛事件，监测初判Ⅳ级",
                roads=codes,
            )
            entry["command_seq"] = 1
            project_surfaces(tables)
            return present_entry(entry, tables), []

    # ---------- 生命周期动作（启动/完成/结束） ----------
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"防汛记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于防汛应急可执行范围"
        target = ACTION_RULES[action]
        with store.transaction() as tables:
            row = self._locked_row(tables, entry_id)
            row["status"] = target
            row["防汛状态"] = target
            row["pending"] = target != ENDED_STATUS
            row["abnormal"] = target != ENDED_STATUS and level_index(effective_level(row)) >= 2
            if target == ENDED_STATUS:
                row["恢复时间"] = now_text()
            project_surfaces(tables)
        return self.get_entry(entry_id), f"防汛记录已{action}"

    # ---------- 升级发布（主链路） ----------
    def publish_upgrade(
        self,
        entry_id: int,
        *,
        command_no: str,
        operator: str,
        roads: list[str],
        expected_version: int,
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """发布一档升级命令。

        返回 (记录, 说明, 是否为重复提交)。重复的 command_no 直接回放原结果，
        不新增历史档、不重复通知；版本被并发推进则抛 FloodConflict。
        """
        command_no = command_no.strip()
        operator = operator.strip() or "防汛值班员"
        roads = self._normalize_roads(roads)
        if not command_no:
            return None, "缺少命令编号（command_no），无法留档", False

        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"防汛记录 {entry_id} 不存在或已归档", False

        # 幂等：同一命令编号重复提交（双击/网络重试），回放而不是再推进一版。
        duplicated = self._find_command(command_no)
        if duplicated is not None:
            if int(duplicated.get("id", 0)) != entry_id:
                return None, f"命令编号 {command_no} 已用于其他预警事件，不能重复发布", False
            return self.get_entry(entry_id), f"命令 {command_no} 已发布，重复提交未再次生效", True

        if entry.get("status") == ENDED_STATUS:
            return None, "该预警事件已结束，不能再发布升级命令", False
        current = effective_level(entry)
        target = next_level(current)
        if target is None:
            return None, "已是红色预警（Ⅰ级），不能继续升级；如需更强措施请走应急调度流程", False

        valid_codes = {str(row.get("路段编号", "")) for row in store.rows(ROAD)}
        missing = [code for code in roads if code not in valid_codes]
        if not roads:
            return None, "发布前必须核对并确认至少一条影响路段", False
        if missing:
            return None, f"影响路段 {('、'.join(missing))} 不在管养路段台账内，请重新核对", False

        with store.transaction() as tables:
            row = self._locked_row(tables, entry_id)
            # 乐观锁：并发值守只允许推进一版，后到者必须基于新版本重新确认。
            if int(row.get("version", 1)) != int(expected_version):
                raise FloodConflict(
                    f"该事件刚被其他值班员推进到 v{row.get('version')}，"
                    "请刷新核对最新级别后再发布"
                )
            append_history(
                row,
                source=SOURCE_COMMAND,
                level=target,
                command_no=command_no,
                operator=operator,
                note=note or f"指挥部发布{target}（{fd.LEVEL_ORDERS[level_index(target)]}）",
                roads=roads,
            )
            row["road_codes"] = roads
            row["updated_at"] = now_text()
            project_surfaces(tables)  # 通知 / 排水任务 / 风险面同一事务提交
        return self.get_entry(entry_id), f"已发布{target}，防汛档案、通知栏、排水任务与道路风险面同步更新", False

    # ---------- 自动监测 ----------
    def report_monitoring(
        self,
        entry_id: int,
        *,
        level: str,
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        if level not in fd.LEVELS:
            return None, f"监测级别「{level}」不在预警阶梯内"
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"防汛记录 {entry_id} 不存在或已归档"
        if entry.get("status") == ENDED_STATUS:
            return None, "事件已结束，监测数据不再更新"
        with store.transaction() as tables:
            row = self._locked_row(tables, entry_id)
            row["监测级别"] = level
            append_history(
                row,
                source=SOURCE_MONITOR,
                level=level,
                operator="自动监测",
                note=note or f"自动监测更新为{level}（如已有指挥部命令，以命令为准）",
            )
            row["updated_at"] = now_text()
            project_surfaces(tables)
        return self.get_entry(entry_id), f"监测数据已更新为{level}；当前生效级别为{effective_level(entry)}"

    # ---------- 通知栏 ----------
    def active_notices(self) -> list[dict[str, Any]]:
        return [dict(row) for row in store.rows(NOTICE_MODULE) if row.get("active")]

    # ---------- 道路风险工作台 ----------
    def risk_board(self) -> dict[str, Any]:
        tables = store.tables()
        drains = tables.get(DRAINAGE, [])
        road_rows: list[dict[str, Any]] = []
        for road in tables.get(ROAD, []):
            code = str(road.get("路段编号", ""))
            linked = [d for d in drains if str(d.get("所属路段", "")) == code]
            pending_tasks = [
                d for d in linked if str(d.get("排水任务状态", "")) != fd.DRAINAGE_TASK_IDLE
            ]
            road_rows.append({
                "路段编号": code,
                "路段名称": road.get("路段名称", ""),
                "起止桩号": road.get("起止桩号", ""),
                "风险等级": road.get("风险等级", fd.RISK_IDLE_LEVEL),
                "风险面状态": road.get("风险面状态", fd.ROAD_RISK_IDLE),
                "关联防汛记录": road.get("关联防汛记录", ""),
                "排水设施数": len(linked),
                "待办排水任务": len(pending_tasks),
            })
        road_rows.sort(
            key=lambda item: (
                0 if item["风险等级"] != fd.RISK_IDLE_LEVEL else 1,
                -level_index(item["风险等级"]) if item["风险等级"] in fd.LEVELS else 0,
                item["路段编号"],
            )
        )
        drain_tasks = [
            {
                "设施编号": d.get("设施编号", ""),
                "所属路段": d.get("所属路段", ""),
                "设施类型": d.get("设施类型", ""),
                "预警级别": d.get("预警级别", ""),
                "排水任务状态": d.get("排水任务状态", fd.DRAINAGE_TASK_IDLE),
                "关联防汛记录": d.get("关联防汛记录", ""),
            }
            for d in drains
            if str(d.get("排水任务状态", "")) != fd.DRAINAGE_TASK_IDLE
        ]
        level_counts = {level: 0 for level in fd.LEVELS}
        for road in road_rows:
            if road["风险等级"] in level_counts:
                level_counts[road["风险等级"]] += 1
        return {
            "roads": road_rows,
            "drain_tasks": drain_tasks,
            "stats": {
                "风险路段": sum(1 for r in road_rows if r["风险等级"] != fd.RISK_IDLE_LEVEL),
                "待办排水任务": len(drain_tasks),
                "生效预警事件": len(self.active_notices()),
                "级别分布": level_counts,
            },
        }

    # ---------- 内部工具 ----------
    def _locked_row(self, tables: dict[str, list[dict[str, Any]]], entry_id: int) -> dict[str, Any]:
        for row in tables[MODULE]:
            if int(row.get("id", 0)) == entry_id:
                return row
        raise RuntimeError(f"事务内未找到防汛记录 {entry_id}")

    def _find_command(self, command_no: str) -> dict[str, Any] | None:
        for entry in store.rows(MODULE):
            for item in entry.get("history", []):
                if item.get("source") == SOURCE_COMMAND and item.get("command_no") == command_no:
                    return entry
        return None

    @staticmethod
    def _normalize_roads(value: Any) -> list[str]:
        """影响路段入参兼容列表与逗号/顿号分隔字符串。"""
        if isinstance(value, (list, tuple, set)):
            parts = [str(code) for code in value]
        else:
            text = str(value or "").replace("，", ",").replace("、", ",")
            parts = text.split(",")
        return [part.strip() for part in parts if part.strip()]
