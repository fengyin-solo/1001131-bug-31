"""防汛应急接口：防汛档案维护，以及预警升级链路（核对路段、发布升级、自动监测）。

升级三步由前端依次调用：
1. GET  /api/flood/{id}             定位预警事件；
2. POST /api/flood/{id}/check       核对影响路段，领取 check_token；
3. POST /api/flood/{id}/escalate    凭 token 发布升级（通知/任务/风险面同事务提交）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.flood import FloodService
from app.services.flood_watch import LEVELS, RISK_TABLE, watch_service
from app.store import store

router = APIRouter(prefix="/api/flood", tags=["防汛应急"])

service = FloodService()

LIST_FIELDS = ["记录编号", "预警级别", "影响路段", "积水深度", "应急措施", "投入人员", "恢复时间", "防汛状态"]
STATUSES = ["待响应", "响应中", "已处置", "已结束"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按记录编号检索"),
    status: str | None = Query(default=None, description="待响应、响应中、已处置、已结束"),
    level: str | None = Query(default=None, description="蓝色预警、黄色预警、橙色预警、红色预警"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按记录编号、状态与预警级别过滤防汛应急列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, level=level, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/notifications/active")
def active_notifications() -> dict[str, Any]:
    """通知栏：当前未结束事件的生效预警，按级别从高到低返回。"""
    return {"items": watch_service.list_notifications(), "levels": LEVELS}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条防汛记录明细，附带级别阶梯、历史命令与当前联动状态。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"防汛记录 {entry_id} 不存在或已归档")
    return {
        **entry,
        "生效级别": watch_service.effective_level(entry),
        "级别阶梯": LEVELS,
        "历史命令": watch_service.list_commands(entry_id),
        "排水任务": watch_service.list_drainage_tasks(entry_id),
        "道路风险面": [
            row for row in store.rows(RISK_TABLE)
            if int(row.get("事件id", 0)) == entry_id
        ],
    }


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条防汛记录，缺字段或级别不在阶梯内时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"校验未通过：{'、'.join(missing)}")
    return ActionResult(ok=True, message="防汛记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条防汛记录执行启动响应、完成处置、结束响应；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/check", response_model=ActionResult)
def check_sections(entry_id: int) -> ActionResult:
    """核对影响路段：交叉排水设施与管养路段台账，返回核对凭证供发布升级使用。"""
    payload, message = watch_service.check_affected_sections(entry_id)
    if payload is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="影响路段核对完成，可发布升级", entry=payload)


@router.post("/{entry_id}/escalate", response_model=ActionResult)
def escalate(entry_id: int, payload: EntryPayload) -> ActionResult:
    """发布预警升级：只能推进相邻一级，通知/排水任务/道路风险面在同一事务内提交。"""
    values = payload.values
    target_level = str(values.get("target_level") or values.get("预警级别") or "").strip()
    result, message = watch_service.escalate(
        entry_id,
        target_level,
        operator=str(values.get("operator") or "防汛值班员"),
        check_token=str(values.get("check_token") or ""),
        expected_version=values.get("expected_version"),
        remark=payload.remark or "",
    )
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/{entry_id}/monitoring", response_model=ActionResult)
def report_monitoring(entry_id: int, payload: EntryPayload) -> ActionResult:
    """自动监测上报建议级别；指挥部已下命令时建议值不改变生效级别。"""
    suggested = str(payload.values.get("suggested_level") or "").strip()
    result, message = watch_service.report_monitoring(entry_id, suggested)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="自动监测建议已记录", entry=result)


@router.get("/{entry_id}/drainage-tasks")
def drainage_tasks(entry_id: int) -> dict[str, Any]:
    """该预警事件派生的排水任务清单。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"防汛记录 {entry_id} 不存在或已归档")
    return {"items": watch_service.list_drainage_tasks(entry_id)}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出防汛应急清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "flood", "total": total, "items": items}
