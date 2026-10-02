<template>
  <section class="page" data-module="flood">
    <header class="page-head">
      <div>
        <h2>防汛应急管理</h2>
        <p class="page-desc">维护防汛记录，围绕记录编号、预警级别、影响路段、积水深度做登记、筛选与状态流转。升级需进入详情按“定位事件 → 核对路段 → 发布升级”执行。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记防汛记录</button>
        <button class="btn" type="button" @click="exportRows">导出防汛应急清单</button>
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
          <td>{{ row['记录编号'] ?? '—' }}</td>
          <td>
            <span class="level-tag" :class="levelClass(String(row['预警级别'] ?? ''))">{{ row['预警级别'] ?? '—' }}</span>
          </td>
          <td>{{ row['影响路段'] ?? '—' }}</td>
          <td>{{ row['积水深度'] ?? '—' }}</td>
          <td>{{ row['应急措施'] ?? '—' }}</td>
          <td>{{ row['投入人员'] ?? '—' }}</td>
          <td>{{ row['恢复时间'] || '—' }}</td>
          <td>{{ row['防汛状态'] ?? row.status ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看/升级</button>
            <template v-if="row.status !== '已结束'">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无防汛应急数据，可先登记防汛记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条防汛应急记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'
import { levelClass, useNoticeStore } from '@/stores/notice'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/flood'
const columns = ["记录编号", "预警级别", "影响路段", "积水深度", "应急措施", "投入人员", "恢复时间", "防汛状态"]
const actions = ["启动响应", "完成处置", "结束响应"]

const router = useRouter()
const notices = useNoticeStore()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = computed(() => {
  const waiting = rows.value.filter((row) => row.status === '待响应').length
  const responding = rows.value.filter((row) => row.status === '响应中').length
  const resolved = rows.value.filter((row) => row.status === '已处置' || row.status === '已结束').length
  return [
    { label: '待响应记录', value: waiting },
    { label: '响应中记录', value: responding },
    { label: '已处置/结束记录', value: resolved },
  ]
})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '防汛记录登记入口尚未接入审批流'
}

function openDetail(row: Row) {
  void router.push(`/flood/${row.id}`)
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('防汛应急动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message || '防汛应急动作未生效')
    await reload()
    await notices.refresh()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '防汛应急操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('防汛记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '防汛应急列表读取失败'
  }
}

onMounted(reload)
</script>
