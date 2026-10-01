<template>
  <section class="page" data-module="drainage">
    <header class="page-head">
      <div>
        <h2>排水设施管理</h2>
        <p class="page-desc">维护排水设施，围绕设施编号、设施类型、所属路段、桩号位置做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记排水设施</button>
        <button class="btn" type="button" @click="exportRows">导出排水设施清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无排水设施数据，可先登记排水设施</td>
        </tr>
      </tbody>
    </table>

    <div class="detail-card" data-module="flood-drainage-tasks">
      <h3>防汛联动排水任务</h3>
      <p class="page-desc">由在警预警事件派生，随预警级别同步对齐（值守巡查 → 预抽排待命 → 强制抽排 → 抢险抽排）。</p>
      <table class="data-table">
        <thead>
          <tr><th>记录编号</th><th>影响路段</th><th>预警级别</th><th>任务状态</th><th>更新时间</th><th>链路</th></tr>
        </thead>
        <tbody>
          <tr v-for="task in linkedTasks" :key="String(task.id)">
            <td>{{ task.记录编号 }}</td>
            <td>{{ task.影响路段 }}</td>
            <td><span class="level-badge" :class="levelClass(String(task.预警级别))">{{ task.预警级别 }}</span></td>
            <td>{{ task.任务状态 }}</td>
            <td>{{ task.更新时间 }}</td>
            <td><button class="link" type="button" @click="openEvent(task.事件id)">查看事件</button></td>
          </tr>
          <tr v-if="!linkedTasks.length">
            <td colspan="6" class="empty-state">当前没有在警事件派生的排水任务</td>
          </tr>
        </tbody>
      </table>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条排水设施记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchJson, request } from '@/api/client'
import { floodBus } from '@/stores/floodBus'

type Row = Record<string, string | number | null>
type LinkedTask = Record<string, string | number | null>

const ENDPOINT = '/api/drainage'
const columns = ["设施编号", "设施类型", "所属路段", "桩号位置", "清理日期", "淤积程度", "管养班组", "设施状态"]
const actions = ["安排清淤", "安排疏通", "登记损坏"]
const statuses = ["正常", "淤积", "堵塞", "损坏"]
const stats = [{"label": "正常设施", "value": 0}, {"label": "淤积设施", "value": 0}, {"label": "损坏设施", "value": 0}]

const rows = ref<Row[]>([])
const linkedTasks = ref<LinkedTask[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const router = useRouter()

function levelClass(value: string): string {
  return {
    蓝色预警: 'lv-blue',
    黄色预警: 'lv-yellow',
    橙色预警: 'lv-orange',
    红色预警: 'lv-red',
  }[value] ?? 'lv-blue'
}

function openEvent(id: unknown) {
  void router.push({ name: 'flood-detail', params: { id: String(id) } })
}

async function loadLinkedTasks() {
  try {
    const notices = await fetchJson<{ items: Array<{ 事件id: number }> }>('/api/flood/notifications/active')
    const groups = await Promise.all(
      (notices.items ?? []).map((n) =>
        fetchJson<{ items: LinkedTask[] }>(`/api/flood/${n.事件id}/drainage-tasks`),
      ),
    )
    linkedTasks.value = groups.flatMap((g) => g.items ?? [])
  } catch {
    linkedTasks.value = []
  }
}

watch(() => floodBus.noticeTick, () => loadLinkedTasks())

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '排水设施登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('排水设施动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '排水设施操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('排水设施列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '排水设施列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadLinkedTasks()
})
</script>
