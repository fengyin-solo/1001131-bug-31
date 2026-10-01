"""防汛应急业务规则：防汛档案的登记、筛选与生命周期状态流转。

预警升级链路（预警记录 -> 通知栏 -> 排水任务 -> 道路风险面）由
``app.services.flood_watch.watch_service`` 统一负责：
- 登记防汛记录时按初始级别建立通知/任务/风险面基线；
- 结束响应时联动撤销通知栏与任务/风险面，避免已结束事件仍挂着高等级。
"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.flood_watch import LEVELS, watch_service

MODULE = "flood"
REQUIRED_FIELDS = ["记录编号", "预警级别", "影响路段"]
STATUS_ORDER = ["待响应", "响应中", "已处置", "已结束"]
ACTION_RULES = {"启动响应": "响应中", "完成处置": "已处置", "结束响应": "已结束"}
NEGATIVE_ACTIONS = []
FINAL_STATUSES = {"已处置", "已结束"}


class FloodService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        level: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if level:
            rows = [row for row in rows if row.get("预警级别") == level]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        level = str(values.get("预警级别") or "").strip()
        if level not in LEVELS:
            return None, [f"预警级别必须是 {('、'.join(LEVELS))} 之一"]
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["防汛状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 值守链路基线：初始级别、版本位、自动监测来源，以及联动数据
        entry["预警级别"] = level
        entry["version"] = 1
        entry["来源"] = "自动监测"
        entry["auto_level"] = level
        rows.append(entry)
        watch_service.register_event(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"防汛记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于防汛应急可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["防汛状态"] = target
        entry["pending"] = target not in FINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if target in FINAL_STATUSES:
            self._retire_linked_rows(entry_id)
        return entry, f"防汛记录已{action}"

    @staticmethod
    def _retire_linked_rows(entry_id: int) -> None:
        """结束响应：通知栏撤下该事件，任务与风险面标记已解除，不再停留在高等级。"""
        for notice in [r for r in store.rows("flood_notice") if int(r.get("事件id", 0)) == entry_id]:
            store.rows("flood_notice").remove(notice)
        for table, field in (("flood_drainage_task", "任务状态"), ("flood_road_risk", "管控状态")):
            for row in [r for r in store.rows(table) if int(r.get("事件id", 0)) == entry_id]:
                row[field] = "已解除"
