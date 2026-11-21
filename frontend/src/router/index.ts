import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
const SourceBinding = () => import('@/views/source_binding/index.vue')
const CdcTask = () => import('@/views/cdc_task/index.vue')
const StreamTransform = () => import('@/views/stream_transform/index.vue')
const WindowAgg = () => import('@/views/window_agg/index.vue')
const StateStore = () => import('@/views/state_store/index.vue')
const RuleEngine = () => import('@/views/rule_engine/index.vue')
const WatermarkMgr = () => import('@/views/watermark_mgr/index.vue')
const SinkWriter = () => import('@/views/sink_writer/index.vue')
const Backpressure = () => import('@/views/backpressure/index.vue')
const Checkpoint = () => import('@/views/checkpoint/index.vue')
const DataQuality = () => import('@/views/data_quality/index.vue')
const SchemaEvolve = () => import('@/views/schema_evolve/index.vue')
const PipelineOrch = () => import('@/views/pipeline_orch/index.vue')
const DedupMgr = () => import('@/views/dedup_mgr/index.vue')
const MetricCalc = () => import('@/views/metric_calc/index.vue')
const EventRouter = () => import('@/views/event_router/index.vue')
const ReplayBatch = () => import('@/views/replay_batch/index.vue')
const GrpPartition = () => import('@/views/grp_partition/index.vue')
const SlotReversal = () => import('@/views/slot_reversal/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/source_binding', name: 'source_binding', component: SourceBinding },
    { path: '/cdc_task', name: 'cdc_task', component: CdcTask },
    { path: '/stream_transform', name: 'stream_transform', component: StreamTransform },
    { path: '/window_agg', name: 'window_agg', component: WindowAgg },
    { path: '/state_store', name: 'state_store', component: StateStore },
    { path: '/rule_engine', name: 'rule_engine', component: RuleEngine },
    { path: '/watermark_mgr', name: 'watermark_mgr', component: WatermarkMgr },
    { path: '/sink_writer', name: 'sink_writer', component: SinkWriter },
    { path: '/backpressure', name: 'backpressure', component: Backpressure },
    { path: '/checkpoint', name: 'checkpoint', component: Checkpoint },
    { path: '/data_quality', name: 'data_quality', component: DataQuality },
    { path: '/schema_evolve', name: 'schema_evolve', component: SchemaEvolve },
    { path: '/pipeline_orch', name: 'pipeline_orch', component: PipelineOrch },
    { path: '/dedup_mgr', name: 'dedup_mgr', component: DedupMgr },
    { path: '/metric_calc', name: 'metric_calc', component: MetricCalc },
    { path: '/event_router', name: 'event_router', component: EventRouter },
    { path: '/replay_batch', name: 'replay_batch', component: ReplayBatch },
    { path: '/grp_partition', name: 'grp_partition', component: GrpPartition },
    { path: '/slot_reversal', name: 'slot_reversal', component: SlotReversal },
  ],
})

export default router
