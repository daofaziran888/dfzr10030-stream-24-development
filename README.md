# 管道工坊 · 实时数仓与流式管道平台

面向实时数据接入、流式转换、变更捕获、窗口聚合、状态管理、断流恢复与多维数据集下发的实时数仓与流式管道开发平台。

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
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 源端绑定 | `source_binding` | 数据源端 | 源端编号、源端类型、连接地址 |
| 变更捕获 | `cdc_task` | CDC任务 | 任务编号、源数据库、监控表 |
| 流式转换 | `stream_transform` | 转换算子 | 算子编号、输入流、输出流 |
| 窗口聚合 | `window_agg` | 时间窗口 | 窗口编号、聚合指标、窗口类型 |
| 状态管理 | `state_store` | 算子状态 | 状态编号、关联算子、存储后端 |
| 规则引擎 | `rule_engine` | 业务规则 | 规则编号、规则条件、触发动作 |
| 水位管理 | `watermark_mgr` | 事件水位 | 水位编号、关联流、水位类型 |
| 数据落盘 | `sink_writer` | 输出槽位 | 槽位编号、输出类型、目标地址 |
| 背压控制 | `backpressure` | 背压策略 | 策略编号、关联算子、队列上限 |
| 断流恢复 | `checkpoint` | 检查点 | 检查点编号、关联流水线、位点时间 |
| 流式质检 | `data_quality` | 质检规则 | 规则编号、关联流、检查项 |
| Schema演进 | `schema_evolve` | 结构变更 | 变更编号、关联流、变更类型 |
| 管道编排 | `pipeline_orch` | 管道DAG | 管道编号、管道名称、节点列表 |
| 去重管理 | `dedup_mgr` | 去重策略 | 策略编号、关联流、去重键 |
| 指标计算 | `metric_calc` | 实时指标 | 指标编号、指标名称、计算公式 |
| 事件路由 | `event_router` | 路由规则 | 规则编号、事件类型、匹配条件 |
| 历史回放 | `replay_batch` | 回放任务 | 任务编号、数据源、起始时间 |
| 分组分区 | `grp_partition` | 分组策略 | 策略编号、关联流、分区键 |
| 槽位更正回退 | `slot_reversal` | 冲销对账批 | 对账批号、目标批次、冲销槽位 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 槽位更正回退

数据落盘过去只有成功回执，错批没有撤销记录。`slot_reversal` 模块为指标槽位引入
版本化账本与槽位冲销对账批归档（`backend/app/services/slot_reversal.py`）：

- 发布按请求标识幂等结算，并发重复请求只结算一次，成功回执同步返回实际已生效的槽位；
- 冲销对账批根据已写入的指标值与各槽位有效版本产出，条目指到具体槽位和版本；
- 提交记录不可变落盘（临时文件 + fsync + 原子改名），落库失败不修改持久结果；
- 错批待冲销而更正同时提交时，立即回退优先、更正链接其后；消费方任意时刻只读到
  一个有来源且已确认的版本，全部版本留档可复查；
- 去重管理依据已结算的冲销对账批确认已撤回的发布标识；
- 重放提交记录可重建槽位清单并回写，核对原批与更正批的实际写入。

归档目录默认为 `backend/data/slot_reversal/`（`app.config.settings.slot_archive_dir`）。
验收测试覆盖交错送达的冲销与更正回执及一次落盘失败：

```bash
cd backend && .venv/bin/python -m pytest tests/test_slot_reversal.py
```

领域：数据工程
子方向：数仓与数据湖
