"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    """状态动作使用独立契约，避免与登记的 values 载荷混用。"""

    action: str
    remark: str | None = None



class SourceBindingEntry(BaseModel):
    """数据源端明细结构。"""

    field_0: str | None = None  # 源端编号
    field_1: str | None = None  # 源端类型
    field_2: str | None = None  # 连接地址
    field_3: str | None = None  # 认证凭证
    field_4: str | None = None  # 心跳间隔
    field_5: str | None = None  # 重连策略
    field_6: str | None = None  # 并发分区
    field_7: str | None = None  # 绑定状态

class CdcTaskEntry(BaseModel):
    """CDC任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 源数据库
    field_2: str | None = None  # 监控表
    field_3: str | None = None  # 操作类型
    field_4: str | None = None  # 起始位点
    field_5: str | None = None  # 当前位点
    field_6: str | None = None  # 延迟毫秒
    field_7: str | None = None  # 异常计数

class StreamTransformEntry(BaseModel):
    """转换算子明细结构。"""

    field_0: str | None = None  # 算子编号
    field_1: str | None = None  # 输入流
    field_2: str | None = None  # 输出流
    field_3: str | None = None  # 转换类型
    field_4: str | None = None  # 并行实例
    field_5: str | None = None  # 背压阈值
    field_6: str | None = None  # 状态大小
    field_7: str | None = None  # 算子耗时

class WindowAggEntry(BaseModel):
    """时间窗口明细结构。"""

    field_0: str | None = None  # 窗口编号
    field_1: str | None = None  # 聚合指标
    field_2: str | None = None  # 窗口类型
    field_3: str | None = None  # 窗口长度
    field_4: str | None = None  # 滑动步长
    field_5: str | None = None  # 迟到阈值
    field_6: str | None = None  # 发射频率
    field_7: str | None = None  # 状态过期

class StateStoreEntry(BaseModel):
    """算子状态明细结构。"""

    field_0: str | None = None  # 状态编号
    field_1: str | None = None  # 关联算子
    field_2: str | None = None  # 存储后端
    field_3: str | None = None  # 分区数量
    field_4: str | None = None  # 状态大小
    field_5: str | None = None  # 过期策略
    field_6: str | None = None  # 快照周期
    field_7: str | None = None  # 最后快照

class RuleEngineEntry(BaseModel):
    """业务规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 规则条件
    field_2: str | None = None  # 触发动作
    field_3: str | None = None  # 优先级
    field_4: str | None = None  # 生效范围
    field_5: str | None = None  # 冷却秒数
    field_6: str | None = None  # 命中次数
    field_7: str | None = None  # 最后触发

class WatermarkMgrEntry(BaseModel):
    """事件水位明细结构。"""

    field_0: str | None = None  # 水位编号
    field_1: str | None = None  # 关联流
    field_2: str | None = None  # 水位类型
    field_3: str | None = None  # 当前水位
    field_4: str | None = None  # 允许迟到
    field_5: str | None = None  # 空闲超时
    field_6: str | None = None  # 水位间隔
    field_7: str | None = None  # 最后更新

class SinkWriterEntry(BaseModel):
    """输出槽位明细结构。"""

    field_0: str | None = None  # 槽位编号
    field_1: str | None = None  # 输出类型
    field_2: str | None = None  # 目标地址
    field_3: str | None = None  # 写入模式
    field_4: str | None = None  # 批次大小
    field_5: str | None = None  # 刷新间隔
    field_6: str | None = None  # 压缩算法
    field_7: str | None = None  # 分区策略

class BackpressureEntry(BaseModel):
    """背压策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 关联算子
    field_2: str | None = None  # 队列上限
    field_3: str | None = None  # 扩容阈值
    field_4: str | None = None  # 降级动作
    field_5: str | None = None  # 恢复阈值
    field_6: str | None = None  # 触发次数
    field_7: str | None = None  # 当前状态

class CheckpointEntry(BaseModel):
    """检查点明细结构。"""

    field_0: str | None = None  # 检查点编号
    field_1: str | None = None  # 关联流水线
    field_2: str | None = None  # 位点时间
    field_3: str | None = None  # 状态大小
    field_4: str | None = None  # 触发方式
    field_5: str | None = None  # 存活轮数
    field_6: str | None = None  # 恢复耗时
    field_7: str | None = None  # 创建时间

class DataQualityEntry(BaseModel):
    """质检规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 关联流
    field_2: str | None = None  # 检查项
    field_3: str | None = None  # 上限阈值
    field_4: str | None = None  # 下限阈值
    field_5: str | None = None  # 告警级别
    field_6: str | None = None  # 统计窗口
    field_7: str | None = None  # 连续异常

class SchemaEvolveEntry(BaseModel):
    """结构变更明细结构。"""

    field_0: str | None = None  # 变更编号
    field_1: str | None = None  # 关联流
    field_2: str | None = None  # 变更类型
    field_3: str | None = None  # 新增字段
    field_4: str | None = None  # 删除字段
    field_5: str | None = None  # 兼容级别
    field_6: str | None = None  # 生效版本
    field_7: str | None = None  # 回滚标记

class PipelineOrchEntry(BaseModel):
    """管道DAG明细结构。"""

    field_0: str | None = None  # 管道编号
    field_1: str | None = None  # 管道名称
    field_2: str | None = None  # 节点列表
    field_3: str | None = None  # 依赖拓扑
    field_4: str | None = None  # 并行度
    field_5: str | None = None  # 恢复策略
    field_6: str | None = None  # 超时分钟
    field_7: str | None = None  # 运行批次

class DedupMgrEntry(BaseModel):
    """去重策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 关联流
    field_2: str | None = None  # 去重键
    field_3: str | None = None  # 去重窗口
    field_4: str | None = None  # 保留策略
    field_5: str | None = None  # 状态上限
    field_6: str | None = None  # 命中次数
    field_7: str | None = None  # 误杀率

class MetricCalcEntry(BaseModel):
    """实时指标明细结构。"""

    field_0: str | None = None  # 指标编号
    field_1: str | None = None  # 指标名称
    field_2: str | None = None  # 计算公式
    field_3: str | None = None  # 更新频率
    field_4: str | None = None  # 维度组合
    field_5: str | None = None  # 精度模式
    field_6: str | None = None  # 缓存窗口
    field_7: str | None = None  # 最后计算

class EventRouterEntry(BaseModel):
    """路由规则明细结构。"""

    field_0: str | None = None  # 规则编号
    field_1: str | None = None  # 事件类型
    field_2: str | None = None  # 匹配条件
    field_3: str | None = None  # 目标管道
    field_4: str | None = None  # 优先级
    field_5: str | None = None  # 分区键
    field_6: str | None = None  # 重试上限
    field_7: str | None = None  # DLQ策略

class ReplayBatchEntry(BaseModel):
    """回放任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 数据源
    field_2: str | None = None  # 起始时间
    field_3: str | None = None  # 截止时间
    field_4: str | None = None  # 回放倍速
    field_5: str | None = None  # 并行分区
    field_6: str | None = None  # 当前位点
    field_7: str | None = None  # 跳过策略

class GrpPartitionEntry(BaseModel):
    """分组策略明细结构。"""

    field_0: str | None = None  # 策略编号
    field_1: str | None = None  # 关联流
    field_2: str | None = None  # 分区键
    field_3: str | None = None  # 分区数量
    field_4: str | None = None  # 分区算法
    field_5: str | None = None  # 热点检测
    field_6: str | None = None  # 再平衡触发
    field_7: str | None = None  # 左右迁移

class SlotReversalEntry(BaseModel):
    """冲销对账批明细结构。"""

    field_0: str | None = None  # 对账批号
    field_1: str | None = None  # 目标批次
    field_2: str | None = None  # 冲销槽位
    field_3: str | None = None  # 回退条目
    field_4: str | None = None  # 归档序号
    field_5: str | None = None  # 发起原因
    field_6: str | None = None  # 撤销标识
    field_7: str | None = None  # 状态
