# 市政道路桥梁养护管理平台

覆盖道路巡查、桥隧定检、路面病害、交安设施、绿化管养、除雪防汛及养护工程管理的市政道桥全要素养护后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 路段管理 | `road_section` | 管养路段 | 路段编号、路段名称、起止桩号 |
| 日常巡查 | `patrol` | 巡查记录 | 巡查编号、巡查路段、巡查日期 |
| 路面病害 | `pavement` | 病害记录 | 病害编号、所属路段、病害类型 |
| 桥梁定检 | `bridge` | 检测记录 | 检测编号、桥梁名称、检测类型 |
| 桥梁档案 | `bridge_info` | 桥梁 | 桥梁编号、桥梁名称、桥型结构 |
| 隧道管养 | `tunnel` | 隧道 | 隧道编号、隧道名称、隧道长度 |
| 交安设施 | `traffic_facility` | 交安设施 | 设施编号、设施类型、所属路段 |
| 排水设施 | `drainage` | 排水设施 | 设施编号、设施类型、所属路段 |
| 绿化管养 | `green` | 绿化区域 | 区域编号、区域名称、植物品种 |
| 路灯照明 | `lighting` | 路灯设施 | 灯具编号、灯具类型、功率 |
| 除雪防滑 | `winter` | 除雪作业 | 作业编号、作业路段、作业日期 |
| 防汛应急 | `flood` | 防汛记录 | 记录编号、预警级别、影响路段 |
| 边坡防护 | `slope` | 边坡 | 边坡编号、所属路段、边坡类型 |
| 伸缩缝管理 | `expansion` | 伸缩缝 | 缝编号、所属桥梁、缝类型 |
| 支座维护 | `bearing` | 桥梁支座 | 支座编号、所属桥梁、支座类型 |
| 养护工程 | `project` | 养护工程 | 工程编号、工程名称、工程类型 |
| 养护车辆 | `vehicle` | 养护车辆 | 车辆编号、车辆类型、车牌号 |
| 养护材料 | `material` | 养护材料 | 材料编号、材料名称、材料类别 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 防汛预警升级链路

防汛值班员在「防汛应急」列表进入记录详情，按 **定位预警事件 → 核对影响路段 →
发布升级** 三步推进，升级结果同时落到四个面：

| 面 | 落点 | 说明 |
| --- | --- | --- |
| 防汛档案 | `flood` 记录的 `预警级别` / `version` / `history` | 历史阶梯按次留档（自动监测 / 指挥部命令 / 存量迁移） |
| 通知栏 | `GET /api/flood/notices/active` | 一个事件一条，全局 `NoticeBar` 按生效级别变色 |
| 排水任务 | `drainage` 行的 `预警级别` / `排水任务状态` | 仅展示投影，设施状态动作仍走排水模块 |
| 道路风险面 | `road_section` 行的 `风险等级` / `风险面状态` | 多起事件覆盖同一路段取最高级；工作台在 `/risk-board` |

规则（收口于 `backend/app/flood_domain.py`）：

- 四级阶梯 `蓝色(Ⅳ) → 黄色(Ⅲ) → 橙色(Ⅱ) → 红色(Ⅰ)`，每次命令只允许推进相邻一级；
- 指挥部最新命令覆盖自动监测建议，监测上报不改变命令生效级别；
- `command_no` 幂等：重复点击/网络重试不产生第二档历史、第二条通知；
- `version` 乐观锁：并发值守只推进一版，后到发布收到 `409`，刷新核对后再发；
- 通知、任务、风险面与档案在同一事务（`store.transaction()` 快照）内提交，
  任一步失败整体回滚，维持此前级别；
- 存量跳级记录在服务启动时迁回相邻节点（如蓝→红校正为蓝→黄），并追加
  “存量迁移”历史档留痕；
- 相关接口：`POST /api/flood/{id}/upgrade`、`POST /api/flood/{id}/monitor`、
  `GET /api/flood/{id}/history`、`GET /api/flood/risk-board`。
