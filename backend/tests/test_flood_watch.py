"""防汛值守链路测试：升级联动、并发版本、幂等、命令覆盖、跳级迁移与事务回滚。

纯标准库运行：python3 -m unittest discover -s tests
"""
from __future__ import annotations

import importlib
import threading
import unittest

from app import seed as seed_module
from app import store as store_module
from app.services import flood as flood_service_module
from app.services import flood_watch as flood_watch_module


def fresh_runtime():
    """重新装载种子与服务，拿到一套干净的内存仓库（单例 store 会缓存）。"""
    importlib.reload(seed_module)
    importlib.reload(store_module)
    importlib.reload(flood_watch_module)
    importlib.reload(flood_service_module)
    watch = flood_watch_module.watch_service
    watch.bootstrap()
    store = store_module.store
    flood_service = flood_service_module.FloodService()
    return watch, store, flood_service


class FloodWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.watch, self.store, self.flood_service = fresh_runtime()

    def _check_token(self, event_id: int) -> str:
        payload, message = self.watch.check_affected_sections(event_id)
        self.assertIsNotNone(payload, message)
        return payload["check_token"]

    def test_legacy_skip_level_migrates_to_adjacent_node(self) -> None:
        """存量红色跳级记录（无中间命令）应迁回蓝色的相邻节点：黄色，并留痕。"""
        event = self.store.find("flood", 2)
        self.assertEqual(event["预警级别"], "黄色预警")
        migrations = self.store.rows("flood_migration")
        self.assertEqual(len(migrations), 1)
        self.assertEqual(migrations[0]["原级别"], "红色预警")
        self.assertEqual(migrations[0]["迁回级别"], "黄色预警")

    def test_escalate_updates_all_four_layers_in_lockstep(self) -> None:
        """蓝 -> 黄升级后：档案、通知栏、排水任务、道路风险面全部对齐到黄色。"""
        token = self._check_token(1)
        result, message = self.watch.escalate(1, "黄色预警", check_token=token)
        self.assertIsNotNone(result, message)

        event = self.store.find("flood", 1)
        self.assertEqual(event["预警级别"], "黄色预警")
        self.assertEqual(event["version"], 2)
        self.assertEqual(event["来源"], "指挥部命令")

        notice = next(n for n in self.store.rows("flood_notice") if n["事件id"] == 1)
        self.assertEqual(notice["级别"], "黄色预警")

        for task in self.watch.list_drainage_tasks(1):
            self.assertEqual(task["预警级别"], "黄色预警")
            self.assertEqual(task["任务状态"], "预抽排待命")

        risks = [r for r in self.store.rows("flood_road_risk") if r["事件id"] == 1]
        for risk in risks:
            self.assertEqual(risk["风险等级"], "中风险")
            self.assertEqual(risk["管控状态"], "减速提示")

    def test_repeat_click_does_not_create_second_event(self) -> None:
        """重复点击同一级别：只有一条通知、一条命令，第二次被幂等拦下。"""
        token = self._check_token(1)
        self.watch.escalate(1, "黄色预警", check_token=token)

        notices_before = [n for n in self.store.rows("flood_notice") if n["事件id"] == 1]
        commands_before = self.watch.list_commands(1)
        self.assertEqual(len(notices_before), 1)

        result, message = self.watch.escalate(1, "黄色预警", check_token=token)
        self.assertIsNone(result)
        self.assertIn("请勿重复提交", message)

        notices_after = [n for n in self.store.rows("flood_notice") if n["事件id"] == 1]
        self.assertEqual(len(notices_after), 1)
        self.assertEqual(len(self.watch.list_commands(1)), len(commands_before))

    def test_concurrent_guards_only_one_version_pushed(self) -> None:
        """并发值守两人同时升黄：一人成功，另一人因 version 不匹配失败，只推进一版。"""
        token = self._check_token(1)
        outcomes: list[tuple] = []

        def worker(expected_version: int) -> None:
            outcomes.append(
                self.watch.escalate(
                    1, "黄色预警", check_token=token, expected_version=expected_version
                )
            )

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(1,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        success = [item for item in outcomes if item[0] is not None]
        failure = [item for item in outcomes if item[0] is None]
        self.assertEqual(len(success), 1)
        self.assertEqual(len(failure), 1)
        self.assertIn("推进了一版", failure[0][1])
        self.assertEqual(self.store.find("flood", 1)["version"], 2)
        self.assertEqual(len(self.watch.list_commands(1)), 1)

    def test_must_check_sections_before_publish(self) -> None:
        """未核对影响路段（无 check_token）不允许发布升级。"""
        result, message = self.watch.escalate(1, "黄色预警", check_token="")
        self.assertIsNone(result)
        self.assertIn("先核对影响路段", message)
        # 维持原级别
        self.assertEqual(self.store.find("flood", 1)["预警级别"], "蓝色预警")

    def test_skip_level_publish_rejected(self) -> None:
        """不允许跳级发布：蓝 -> 橙 必须被拦下。"""
        token = self._check_token(1)
        result, message = self.watch.escalate(1, "橙色预警", check_token=token)
        self.assertIsNone(result)
        self.assertIn("相邻节点", message)
        self.assertEqual(self.store.find("flood", 1)["预警级别"], "蓝色预警")

    def test_command_overrides_monitoring(self) -> None:
        """指挥部最新命令覆盖自动监测：监测上报更高建议也不改变生效级别，反之命令升级生效。"""
        # 先命令升到黄色
        token = self._check_token(1)
        self.watch.escalate(1, "黄色预警", check_token=token)
        # 自动监测再报蓝色（降级建议），生效仍是黄
        self.watch.report_monitoring(1, "蓝色预警")
        event = self.store.find("flood", 1)
        self.assertEqual(self.watch.effective_level(event), "黄色预警")

        # 监测建议红色，但未下达命令，生效仍是黄
        result, _ = self.watch.report_monitoring(1, "红色预警")
        self.assertTrue(result["被命令覆盖"])
        self.assertEqual(self.watch.effective_level(event), "黄色预警")

    def test_command_history_ladder_archived_each_time(self) -> None:
        """每次命令都留档：蓝->黄、黄->橙 后历史阶梯有两条，按序次排列。"""
        token = self._check_token(1)
        self.watch.escalate(1, "黄色预警", check_token=token)
        token = self._check_token(1)
        self.watch.escalate(1, "橙色预警", check_token=token, operator="张指挥")

        commands = self.watch.list_commands(1)
        self.assertEqual([c["级别"] for c in commands], ["黄色预警", "橙色预警"])
        self.assertEqual([c["序次"] for c in commands], [1, 2])
        self.assertEqual(commands[1]["发布人"], "张指挥")

    def test_transaction_rollback_keeps_previous_level(self) -> None:
        """事务中道路风险面写入抛错时，通知与任务已做的修改一并回滚，维持此前级别。"""
        token = self._check_token(1)
        original_touch = flood_watch_module.Transaction.touch

        def boom(self, table, row):  # noqa: ANN001
            if table == flood_watch_module.RISK_TABLE:
                raise RuntimeError("风险面写入失败(模拟)")
            return original_touch(self, table, row)

        flood_watch_module.Transaction.touch = boom  # type: ignore[assignment]
        try:
            result, message = self.watch.escalate(1, "黄色预警", check_token=token)
        finally:
            flood_watch_module.Transaction.touch = original_touch  # type: ignore[assignment]

        self.assertIsNone(result)
        self.assertIn("已回滚", message)

        event = self.store.find("flood", 1)
        self.assertEqual(event["预警级别"], "蓝色预警")
        self.assertEqual(event["version"], 1)
        notice = next(n for n in self.store.rows("flood_notice") if n["事件id"] == 1)
        self.assertEqual(notice["级别"], "蓝色预警")
        for task in self.watch.list_drainage_tasks(1):
            self.assertEqual(task["任务状态"], "值守巡查")
        # 命令留档也不应残留在事务外
        self.assertEqual(self.watch.list_commands(1), [])

    def test_road_risk_workbench_aggregates_max_risk_per_section(self) -> None:
        """工作台按路段聚合取最高风险，并附带通知栏。"""
        payload = self.watch.road_risk_workbench()
        names = {item["影响路段"] for item in payload["items"]}
        self.assertIn("南站高架匝口", names)
        self.assertTrue(all("风险等级" in item for item in payload["items"]))
        self.assertGreaterEqual(len(payload["notices"]), 1)
        # 级别从高到低
        ranks = [flood_watch_module.rank(item["预警级别"]) for item in payload["items"]]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_finished_event_excluded_from_notifications(self) -> None:
        """结束响应后通知栏撤下该事件，任务/风险面标记已解除。"""
        self.flood_service.run_action(1, "结束响应")
        notice_ids = {n["事件id"] for n in self.watch.list_notifications()}
        self.assertNotIn(1, notice_ids)
        for task in self.watch.list_drainage_tasks(1):
            self.assertEqual(task["任务状态"], "已解除")

    def test_inactive_event_cannot_escalate(self) -> None:
        """已结束事件不能再核对/发布升级。"""
        self.flood_service.run_action(3, "结束响应")
        token_payload, check_msg = self.watch.check_affected_sections(3)
        self.assertIsNone(token_payload)
        self.assertIn("无需再核对", check_msg)
        result, message = self.watch.escalate(3, "橙色预警", check_token="x")
        self.assertIsNone(result)
        self.assertIn("已结束", message)


if __name__ == "__main__":
    unittest.main()
