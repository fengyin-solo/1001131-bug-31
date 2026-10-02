<template>
  <section class="page" data-module="flood-detail">
    <header class="page-head">
      <div>
        <h2>防汛记录详情 · {{ entry?.['记录编号'] ?? '—' }}</h2>
        <p class="page-desc">沿“定位预警事件 → 核对影响路段 → 发布升级”推进；每次命令只升相邻一级，通知栏、排水任务与道路风险面同事务更新。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn ghost" to="/flood">返回防汛应急列表</RouterLink>
      </div>
    </header>

    <div v-if="errorMessage" class="notice-bar notice-red" style="margin-bottom: 12px">{{ errorMessage }}</div>

    <template v-if="entry">
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">当前预警级别</span>
          <strong class="stat-value">
            <span class="level-tag" :class="levelClass(String(entry['预警级别']))">{{ entry['预警级别'] }}</span>
          </strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">自动监测建议</span>
          <strong class="stat-value">{{ entry['监测级别'] }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">生效来源</span>
          <strong class="stat-value">{{ entry['生效来源'] }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">防汛状态 / 版本</span>
          <strong class="stat-value">{{ entry['防汛状态'] ?? entry.status }} · v{{ entry.version }}</strong>
        </article>
      </div>

      <!-- 升级向导：步骤一已由“从列表进入本页”完成定位 -->
      <div class="wizard">
        <div class="wizard-steps">
          <span class="wizard-step" :class="{ active: step >= 1 }">1 定位预警事件</span>
          <span class="wizard-arrow">→</span>
          <span class="wizard-step" :class="{ active: step >= 2 }">2 核对影响路段</span>
          <span class="wizard-arrow">→</span>
          <span class="wizard-step" :class="{ active: step >= 3 }">3 发布升级</span>
        </div>

        <template v-if="entry.status !== '已结束'">
          <div v-if="next" class="wizard-body">
            <div class="wizard-row">
              <span>本次将升级为：</span>
              <strong><span class="level-tag" :class="levelClass(next)">{{ next }}</span></strong>
              <span class="timeline-meta">只允许沿阶梯推进相邻一级，当前 v{{ entry.version }}</span>
            </div>
            <div class="wizard-row">
              <span>影响路段（发布前必须逐条核对）：</span>
              <label
                v-for="road in allRoads"
                :key="road.code"
                class="road-check"
                :class="{ checked: selectedRoads.includes(road.code) }"
              >
                <input v-model="selectedRoads" type="checkbox" :value="road.code" />
                {{ road.code }} {{ road.name }}
              </label>
            </div>
            <div class="wizard-row">
              <label>
                命令编号：
                <input v-model="commandNo" placeholder="指挥部命令编号，用于留档去重" style="width: 260px" />
              </label>
              <label>
                备注：
                <input v-model="note" placeholder="命令备注（可选）" style="width: 260px" />
              </label>
            </div>
            <div class="wizard-row">
              <button class="btn primary" type="button" :disabled="submitting" @click="publish">
                {{ submitting ? '发布中…' : `发布升级至${next}` }}
              </button>
              <button class="btn" type="button" :disabled="submitting" @click="simulateMonitor">
                同步自动监测（模拟监测升档）
              </button>
              <span class="timeline-meta">重复点击同一命令编号不会产生第二条通知或第二档历史</span>
            </div>
          </div>
          <div v-else class="timeline-meta">已是红色预警（Ⅰ级），阶梯到顶，不能继续升级。</div>
        </template>
        <div v-else class="timeline-meta">该事件已结束，归档保留历史阶梯，不再接受升级。</div>
      </div>

      <!-- 影响面核对：排水任务与道路风险面应与上面级别一致 -->
      <div class="stat-row">
        <article class="stat-card">
          <span class="stat-label">影响路段</span>
          <strong class="stat-value" style="font-size: 14px">{{ entry['影响路段'] || '—' }}</strong>
        </article>
        <article class="stat-card">
          <span class="stat-label">积水深度 / 投入人员</span>
          <strong class="stat-value" style="font-size: 14px">{{ entry['积水深度'] || '—' }} · {{ entry['投入人员'] || '—' }}</strong>
        </article>
      </div>

      <h3 style="font-size: 15px">历史阶梯（每次命令留档，最新命令覆盖自动监测）</h3>
      <ul class="timeline">
        <li
          v-for="item in history"
          :key="`${item.seq}-${item.command_no || item.source}`"
          class="timeline-item"
          :class="`source-${item.source}`"
        >
          <div>
            <span class="level-tag" :class="levelClass(String(item.level))">{{ item.level }}</span>
            <strong>{{ item.source }}</strong>
            <span v-if="item.command_no">· {{ item.command_no }}</span>
            <span>· {{ item.operator }}</span>
          </div>
          <div>{{ item.note }}</div>
          <div class="timeline-meta">{{ item.at }} · 影响 {{ item.roads?.join('、') || '—' }} · 版本 v{{ item.version }}</div>
        </li>
      </ul>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'
import { levelClass, useNoticeStore } from '@/stores/notice'

type HistoryItem = {
  seq: number
  at: string
  source: string
  command_no: string
  operator: string
  level: string
  note: string
  roads: string[]
  version: number
}

type RoadOption = { code: string; name: string }

const LEVELS = ['蓝色预警', '黄色预警', '橙色预警', '红色预警']

const route = useRoute()
const notices = useNoticeStore()
const entryId = Number(route.params.id)

const entry = ref<Record<string, any> | null>(null)
const history = ref<HistoryItem[]>([])
const allRoads = ref<RoadOption[]>([])
const selectedRoads = ref<string[]>([])
const commandNo = ref('')
const note = ref('')
const submitting = ref(false)
const errorMessage = ref('')

const step = computed(() => (selectedRoads.value.length ? 3 : 2))
const next = computed(() => {
  const idx = LEVELS.indexOf(String(entry.value?.['预警级别'] ?? ''))
  return idx >= 0 && idx < LEVELS.length - 1 ? LEVELS[idx + 1] : ''
})

async function load() {
  const [detailResp, historyResp, roadsResp] = await Promise.all([
    request(`/api/flood/${entryId}`),
    request(`/api/flood/${entryId}/history`),
    request('/api/road_section?size=200'),
  ])
  if (!detailResp.ok) {
    errorMessage.value = '防汛记录不存在或已归档'
    return
  }
  const detail = await detailResp.json()
  entry.value = detail
  const historyPayload = historyResp.ok ? await historyResp.json() : { items: [] }
  history.value = historyPayload.items ?? []
  const roadsPayload = roadsResp.ok ? await roadsResp.json() : { items: [] }
  allRoads.value = (roadsPayload.items ?? []).map((row: Record<string, string>) => ({
    code: String(row['路段编号'] ?? ''),
    name: String(row['路段名称'] ?? ''),
  }))
  selectedRoads.value = Array.isArray(detail.road_codes) ? [...detail.road_codes] : []
  const day = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  commandNo.value = `CMD-${day}-${entryId}-${detail.version}`
}

async function publish() {
  if (!entry.value) return
  errorMessage.value = ''
  if (!selectedRoads.value.length) {
    errorMessage.value = '请先核对并勾选至少一条影响路段'
    return
  }
  if (!commandNo.value.trim()) {
    errorMessage.value = '请填写指挥部命令编号'
    return
  }
  submitting.value = true
  try {
    const response = await request(`/api/flood/${entryId}/upgrade`, {
      method: 'POST',
      body: JSON.stringify({
        command_no: commandNo.value.trim(),
        operator: '防汛值班员',
        roads: selectedRoads.value,
        version: Number(entry.value.version),
        note: note.value.trim(),
      }),
    })
    if (response.status === 409) {
      const payload = await response.json().catch(() => ({ detail: '并发冲突，请刷新后重试' }))
      errorMessage.value = payload.detail || '该事件已被其他值班员推进，请刷新核对最新版本'
      await load()
      return
    }
    const payload = await response.json()
    if (!payload.ok && !payload.duplicated) {
      errorMessage.value = payload.message || '升级未生效'
      return
    }
    note.value = ''
    await load()
    await notices.refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '升级发布失败'
  } finally {
    submitting.value = false
  }
}

async function simulateMonitor() {
  errorMessage.value = ''
  const idx = LEVELS.indexOf(String(entry.value?.['监测级别'] ?? '蓝色预警'))
  const target = LEVELS[Math.min(idx + 1, LEVELS.length - 1)]
  const response = await request(`/api/flood/${entryId}/monitor`, {
    method: 'POST',
    body: JSON.stringify({ level: target, note: '值班台同步自动监测数据' }),
  })
  const payload = await response.json()
  if (!payload.ok) {
    errorMessage.value = payload.message
    return
  }
  await load()
  await notices.refresh()
}

onMounted(load)
</script>
