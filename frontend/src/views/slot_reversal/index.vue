<template>
  <section class="page" data-module="slot_reversal">
    <header class="page-head">
      <div>
        <h2>槽位更正回退</h2>
        <p class="page-desc">指标槽位的版本化发布、错批冲销对账与归档重放核对。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-publish" type="button" @click="openPublish">登记指标发布</button>
        <button class="btn" data-testid="open-reversal" type="button" @click="openReversal">登记冲销对账批</button>
        <button class="btn" data-testid="replay" type="button" @click="runReplay">重放对账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="receipt" class="panel" data-testid="receipt-panel">
      <h3 class="panel-title">结算回执 · {{ receipt['回执状态'] }}</h3>
      <p class="panel-line">请求标识 {{ receipt['请求标识'] }} · 批次号 {{ receipt['批次号'] ?? '—' }}</p>
      <p v-if="receipt['失败原因']" class="error-text">{{ receipt['失败原因'] }}</p>
      <table class="data-table">
        <thead>
          <tr><th>槽位</th><th>生效版本</th><th>指标值</th><th>来源批次</th></tr>
        </thead>
        <tbody>
          <tr v-for="(view, slot) in receipt['生效槽位']" :key="String(slot)">
            <td>{{ slot }}</td>
            <td>{{ view ? view['版本'] : '—' }}</td>
            <td>{{ view ? view['指标值'] : '（已置空）' }}</td>
            <td>{{ view ? view['来源批次'] : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3 class="section-title">冲销对账批</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-if="row.status === '待冲销'"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-结算冲销`"
              @click="runAction(row)"
            >
              结算冲销
            </button>
            <span v-else>—</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无冲销对账批，可先登记指标发布再发起回退</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">槽位清单</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in slotColumns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in slotRows" :key="String(row['槽位'])" :data-testid="`slot-${row['槽位']}`">
          <td v-for="column in slotColumns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" :data-testid="`chain-${row['槽位']}`" @click="loadChain(String(row['槽位']))">
              查看冲销链
            </button>
          </td>
        </tr>
        <tr v-if="!slotRows.length">
          <td :colspan="slotColumns.length + 1" class="empty-state">暂无槽位数据，可先登记指标发布</td>
        </tr>
      </tbody>
    </table>

    <div v-if="chainSlot" class="panel" data-testid="chain-panel">
      <h3 class="panel-title">冲销链 · {{ chainSlot }}</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in chainColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in chain" :key="index" :data-status="item['状态']">
            <td v-for="column in chainColumns" :key="column">{{ item[column] ?? '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="replayReport" class="panel" data-testid="replay-panel">
      <h3 class="panel-title">重放对账报告</h3>
      <p class="panel-line">
        重放提交数 {{ replayReport['重放提交数'] }} · 已撤回发布
        {{ replayReport['已撤回发布'].join('、') || '无' }} · 不一致
        {{ replayReport['不一致'].length ? replayReport['不一致'].join('；') : '无' }}
      </p>
      <table class="data-table">
        <thead>
          <tr><th>批次</th><th>请求标识</th><th>已撤回</th><th>实际写入</th></tr>
        </thead>
        <tbody>
          <tr v-for="(batch, batchId) in replayReport['批次写入']" :key="String(batchId)">
            <td>{{ batchId }}</td>
            <td>{{ batch.request_id }}</td>
            <td>{{ batch.withdrawn ? '是' : '否' }}</td>
            <td>{{ formatWrites(batch.writes) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="showPublish" class="modal-backdrop" data-testid="publish-modal">
      <form class="modal" @submit.prevent="submitPublish">
        <h3>登记指标发布</h3>
        <label class="create-field">
          <span>请求标识（同一标识只结算一次）</span>
          <input v-model="publishRequestId" data-testid="publish-request-id" required />
        </label>
        <label class="create-field">
          <span>指标值（每行一条，格式：槽位=值）</span>
          <textarea v-model="publishEntries" data-testid="publish-entries" rows="5" required></textarea>
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showPublish = false">取消</button>
          <button class="btn primary" data-testid="submit-publish" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认发布' }}
          </button>
        </div>
      </form>
    </div>

    <div v-if="showReversal" class="modal-backdrop" data-testid="reversal-modal">
      <form class="modal" @submit.prevent="submitReversal">
        <h3>登记冲销对账批</h3>
        <label class="create-field">
          <span>目标批次（待撤销的发布批次号）</span>
          <input v-model="reversalTarget" data-testid="reversal-target" required />
        </label>
        <label class="create-field">
          <span>发起原因</span>
          <input v-model="reversalReason" data-testid="reversal-reason" />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showReversal = false">取消</button>
          <button class="btn primary" data-testid="submit-reversal" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 笔冲销对账批</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Receipt = Record<string, unknown> & { 生效槽位?: Record<string, Record<string, unknown> | null> }

const ENDPOINT = '/api/slot_reversal'
const columns = ["对账批号", "目标批次", "冲销槽位", "回退条目", "归档序号", "发起原因", "撤销标识", "状态"]
const slotColumns = ["槽位", "有效版本", "指标值", "来源批次", "版本数", "已冲销版本"]
const chainColumns = ["版本", "指标值", "来源批次", "类型", "状态", "回退自版本", "归档序号"]

const rows = ref<Row[]>([])
const total = ref(0)
const slotRows = ref<Row[]>([])
const statValues = ref<Record<string, number>>({})
const chainSlot = ref('')
const chain = ref<Row[]>([])
const receipt = ref<Receipt | null>(null)
const replayReport = ref<Record<string, any> | null>(null)
const errorMessage = ref('')
const showPublish = ref(false)
const showReversal = ref(false)
const submitting = ref(false)
const publishRequestId = ref('')
const publishEntries = ref('')
const reversalTarget = ref('')
const reversalReason = ref('')

const stats = computed(() => [
  { label: '槽位总数', value: statValues.value['槽位总数'] ?? 0 },
  { label: '待冲销对账批', value: statValues.value['待冲销对账批'] ?? 0 },
  { label: '已撤回发布', value: statValues.value['已撤回发布'] ?? 0 },
  { label: '归档提交数', value: statValues.value['归档提交数'] ?? 0 },
])

function formatWrites(writes: Record<string, { version: number; value: unknown; state: string }>): string {
  return Object.entries(writes)
    .map(([slot, item]) => `${slot}#${item.version}=${item.value}（${item.state === 'confirmed' ? '已确认' : '已冲销'}）`)
    .join('；')
}

function parseEntries(text: string): Record<string, unknown> {
  const entries: Record<string, unknown> = {}
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const index = trimmed.indexOf('=')
    if (index <= 0) throw new Error(`无法解析的行：${trimmed}`)
    const slot = trimmed.slice(0, index).trim()
    const raw = trimmed.slice(index + 1).trim()
    const numeric = Number(raw)
    entries[slot] = raw !== '' && !Number.isNaN(numeric) ? numeric : raw
  }
  return entries
}

function openPublish() {
  publishRequestId.value = ''
  publishEntries.value = ''
  errorMessage.value = ''
  showPublish.value = true
}

function openReversal() {
  reversalTarget.value = ''
  reversalReason.value = ''
  errorMessage.value = ''
  showReversal.value = true
}

async function submitPublish() {
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/publish`, {
      method: 'POST',
      body: JSON.stringify({ 请求标识: publishRequestId.value, 指标值: parseEntries(publishEntries.value) }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '发布结算失败')
    receipt.value = payload.entry
    showPublish.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布结算失败'
  } finally {
    submitting.value = false
  }
}

async function submitReversal() {
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reversals`, {
      method: 'POST',
      body: JSON.stringify({ 目标批次: reversalTarget.value, 发起原因: reversalReason.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记冲销对账批失败')
    showReversal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记冲销对账批失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action: '结算冲销' }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '结算冲销未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '结算冲销失败'
  }
}

async function loadChain(slot: string) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/slots/${encodeURIComponent(slot)}/chain`)
    if (!response.ok) throw new Error('冲销链读取失败')
    const payload = await response.json()
    chainSlot.value = slot
    chain.value = payload.items ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '冲销链读取失败'
  }
}

async function runReplay() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/replay`, { method: 'POST' })
    const payload = await response.json()
    replayReport.value = payload.entry
    if (!payload.ok) throw new Error(payload.message || '重放发现不一致')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重放对账失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const [listResponse, slotResponse] = await Promise.all([
      request(ENDPOINT),
      request(`${ENDPOINT}/slots`),
    ])
    if (!listResponse.ok) throw new Error('冲销对账批列表读取失败')
    if (!slotResponse.ok) throw new Error('槽位清单读取失败')
    const listPayload = await listResponse.json()
    const slotPayload = await slotResponse.json()
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    slotRows.value = slotPayload.items ?? []
    statValues.value = slotPayload.stats ?? {}
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '槽位更正回退数据读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title {
  margin: 16px 0 8px;
  font-size: 14px;
}

.panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  padding: 12px;
  margin: 12px 0;
}

.panel-title {
  margin: 0 0 8px;
  font-size: 13px;
}

.panel-line {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--muted);
}

.create-field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-family: inherit;
}
</style>
