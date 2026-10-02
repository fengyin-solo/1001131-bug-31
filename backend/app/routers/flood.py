"""防汛应急接口：维护防汛记录与四级预警升级链路。

升级主链路：定位预警事件（详情） -> 核对影响路段 -> 发布升级。
发布结果在同一事务落到防汛档案、通知栏、排水任务与道路风险面；
版本冲突返回 409，命令重复提交幂等回放。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.flood_domain import LEVELS
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.flood import FloodService, FloodConflict

router = APIRouter(prefix="/api/flood", tags=["防汛应急"])

service = FloodService()

LIST_FIELDS = ["记录编号", "预警级别", "影响路段", "积水深度", "应急措施", "投入人员", "恢复时间", "防汛状态"]
STATUSES = ["待响应", "响应中", "已处置", "已结束"]


class UpgradePayload(BaseModel):
    """发布升级命令：命令编号用于留档与幂等，version 用于并发值守只推进一版。"""

    command_no: str = Field(default="", description="指挥部命令编号，全链路留档与去重")
    operator: str = Field(default="防汛值班员", description="发布值班员")
    roads: list[str] = Field(default_factory=list, description="核对后的影响路段编号")
    version: int = Field(default=1, description="发布前记录的版本号，乐观锁")
    note: str | None = Field(default=None, description="命令备注")


class MonitorPayload(BaseModel):
    level: str = Field(description="自动监测最新级别")
    note: str | None = None


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待响应、响应中、已处置、已结束"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号与状态过滤防汛应急列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/notices/active")
def active_notices() -> dict[str, Any]:
    """通知栏：每个生效中的预警事件一条，级别为命令覆盖监测后的生效级别。"""
    items = service.active_notices()
    top = max(items, key=lambda item: int(item.get("级别序", 0)), default=None)
    return {"items": items, "total": len(items), "top": top}


@router.get("/risk-board")
def risk_board() -> dict[str, Any]:
    """道路风险工作台：路段风险面 + 排水任务待办 + 级别统计。"""
    return service.risk_board()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出防汛应急清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "flood", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条防汛记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"防汛记录 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/history")
def get_history(entry_id: int) -> dict[str, Any]:
    """历史阶梯：每次自动监测、指挥部命令、存量迁移都按时间顺序留档。"""
    history = service.get_history(entry_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"防汛记录 {entry_id} 不存在或已归档")
    return {"items": history, "total": len(history)}


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条防汛记录，缺字段时说明原因而不是静默丢弃。"""
    payload.values.setdefault("road_codes", payload.values.get("影响路段", ""))
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="防汛记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条防汛记录执行启动响应、完成处置、结束响应；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/monitor", response_model=ActionResult)
def report_monitoring(entry_id: int, payload: MonitorPayload) -> ActionResult:
    """上报自动监测级别：只更新监测建议，指挥部最新命令依然覆盖它。"""
    if payload.level not in LEVELS:
        return ActionResult(ok=False, message=f"监测级别必须是：{'、'.join(LEVELS)}")
    entry, message = service.report_monitoring(entry_id, level=payload.level, note=payload.note or "")
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/upgrade", response_model=ActionResult)
def publish_upgrade(entry_id: int, payload: UpgradePayload) -> ActionResult:
    """发布升级：沿阶梯只推进相邻一级，通知/任务/风险面同一事务提交或回滚。

    - 命令编号重复（双击或网络重试）：幂等回放，不产生第二档、第二条通知；
    - 版本号落后（并发值守已推进一版）：409，提示刷新后重新核对。
    """
    try:
        entry, message, duplicated = service.publish_upgrade(
            entry_id,
            command_no=payload.command_no,
            operator=payload.operator,
            roads=payload.roads,
            expected_version=payload.version,
            note=payload.note or "",
        )
    except FloodConflict as conflict:
        raise HTTPException(status_code=409, detail=str(conflict)) from conflict
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry, duplicated=duplicated)
