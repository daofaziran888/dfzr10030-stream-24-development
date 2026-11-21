"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import source_binding as router_source_binding
from app.routers import cdc_task as router_cdc_task
from app.routers import stream_transform as router_stream_transform
from app.routers import window_agg as router_window_agg
from app.routers import state_store as router_state_store
from app.routers import rule_engine as router_rule_engine
from app.routers import watermark_mgr as router_watermark_mgr
from app.routers import sink_writer as router_sink_writer
from app.routers import backpressure as router_backpressure
from app.routers import checkpoint as router_checkpoint
from app.routers import data_quality as router_data_quality
from app.routers import schema_evolve as router_schema_evolve
from app.routers import pipeline_orch as router_pipeline_orch
from app.routers import dedup_mgr as router_dedup_mgr
from app.routers import metric_calc as router_metric_calc
from app.routers import event_router as router_event_router
from app.routers import replay_batch as router_replay_batch
from app.routers import grp_partition as router_grp_partition
from app.routers import slot_reversal as router_slot_reversal

ROUTERS = [router_source_binding, router_cdc_task, router_stream_transform, router_window_agg, router_state_store, router_rule_engine, router_watermark_mgr, router_sink_writer, router_backpressure, router_checkpoint, router_data_quality, router_schema_evolve, router_pipeline_orch, router_dedup_mgr, router_metric_calc, router_event_router, router_replay_batch, router_grp_partition, router_slot_reversal]
