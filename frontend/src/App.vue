<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">管道工坊 · 实时数仓与流式管道平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向实时数据接入、流式转换、变更捕获、窗口聚合、状态管理、断流恢复与多维数据集下发的实时数仓与流式管道开发平台。</span>
        <span class="head-user">当前值班：{{ store.operator }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "源端绑定", path: "/source_binding" }, { label: "变更捕获", path: "/cdc_task" }, { label: "流式转换", path: "/stream_transform" }, { label: "窗口聚合", path: "/window_agg" }, { label: "状态管理", path: "/state_store" }, { label: "规则引擎", path: "/rule_engine" }, { label: "水位管理", path: "/watermark_mgr" }, { label: "数据落盘", path: "/sink_writer" }, { label: "背压控制", path: "/backpressure" }, { label: "断流恢复", path: "/checkpoint" }, { label: "流式质检", path: "/data_quality" }, { label: "Schema演进", path: "/schema_evolve" }, { label: "管道编排", path: "/pipeline_orch" }, { label: "去重管理", path: "/dedup_mgr" }, { label: "指标计算", path: "/metric_calc" }, { label: "事件路由", path: "/event_router" }, { label: "历史回放", path: "/replay_batch" }, { label: "分组分区", path: "/grp_partition" }, { label: "更正回退", path: "/slot_reversal" }]
</script>
