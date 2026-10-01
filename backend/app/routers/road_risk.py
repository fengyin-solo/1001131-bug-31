"""道路风险工作台接口：按影响路段汇总防汛预警派生的道路风险面。"""
from __future__ import annotations

from fastapi import APIRouter

from app.services.flood_watch import LEVELS, ROAD_RISK_CONTROL, ROAD_RISK_LEVEL, watch_service

router = APIRouter(prefix="/api/road-risk", tags=["道路风险工作台"])


@router.get("/workbench")
def workbench() -> dict:
    """风险面按路段聚合，同一路段取最高风险；同时返回当前通知栏。"""
    return watch_service.road_risk_workbench()


@router.get("/legend")
def legend() -> dict:
    """风险等级与管控状态对照：前端配色与文案以此为准，避免和级别错位。"""
    return {
        "levels": LEVELS,
        "风险等级": ROAD_RISK_LEVEL,
        "管控状态": ROAD_RISK_CONTROL,
    }
