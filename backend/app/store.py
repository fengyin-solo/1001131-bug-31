"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

防汛升级链路（通知栏 / 排水任务 / 道路风险面）要求“同一事务提交，失败整体
回滚”，内存实现用一份深拷贝快照模拟事务：transaction() 正常退出才落库，
异常时恢复快照。process_lock 是进程内互斥锁，配合记录上的 version 字段，
保证并发值守只推进一版。
"""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.flood_domain import bootstrap as bootstrap_flood
from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self.process_lock = threading.RLock()
        self.bootstrap_log: dict[str, Any] = {"migrated": []}
        self._bootstrap()

    def _bootstrap(self) -> None:
        self.bootstrap_log = bootstrap_flood(self._tables)

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def tables(self) -> dict[str, list[dict[str, Any]]]:
        return self._tables

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    @contextmanager
    def transaction(self) -> Iterator[dict[str, list[dict[str, Any]]]]:
        """事务上下文：提交前任意一步抛异常，全部改动回滚到进入前状态。"""
        with self.process_lock:
            snapshot = copy.deepcopy(self._tables)
            try:
                yield self._tables
            except Exception:
                # 直接按对象 id 恢复，避免 setdefault 新建的空表残留。
                for name in list(self._tables):
                    if name not in snapshot:
                        del self._tables[name]
                for name, rows in snapshot.items():
                    self._tables[name] = rows
                raise

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
