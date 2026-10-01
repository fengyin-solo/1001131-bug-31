<template>
  <section class="page" data-module="flood">
    <header class="page-head">
      <div>
        <h2>防汛应急管理</h2>
        <p class="page-desc">
          定位预警事件后进入详情，按「核对影响路段 → 发布升级」推进；级别沿蓝→黄→橙→红阶梯，
          通知栏、排水任务与道路风险面同步生效。
        </p>
      </div>
      <div class="page-actions">
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
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>值守状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>预警级别</span>
        <select v-model="level">
          <option value="">全部</option>
          <option v-for="l in levels" :key="l" :value="l">{{ l }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>记录编号</th>
          <th>预警级别</th>
          <th>影响路段</th>
          <th>积水深度</th>
          <th>来源</th>
          <th>版本</th>
          <th>值守状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['记录编号'] ?? '—' }}</td>
          <td><span class="level-badge" :class="levelClass(String(row['预警级别']))">{{ row['预警级别'] }}</span></td>
          <td>{{ sectionText(row['影响路段']) || '—' }}</td>
          <td>{{ row['积水深度'] ?? '—' }}</td>
          <td>{{ row['来源'] ?? '—' }}</td>
          <td>v{{ row.version ?? 1 }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row.id)">详情 / 升级</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无防汛应急记录</td>
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
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, unknown>

const ENDPOINT = '/api/flood'
const levels = ['蓝色预警', '黄色预警', '橙色预警', '红色预警']
const statuses = ['待响应', '响应中', '已处置', '已结束']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const level = ref('')
const stats = ref([
  { label: '在警事件', value: 0 },
  { label: '橙色及以上', value: 0 },
  { label: '今日命令', value: 0 },
])

const router = useRouter()

function levelClass(value: string): string {
  return {
    蓝色预警: 'lv-blue',
    黄色预警: 'lv-yellow',
    橙色预警: 'lv-orange',
    红色预警: 'lv-red',
  }[value] ?? 'lv-blue'
}

function sectionText(value: unknown): string {
  return Array.isArray(value) ? (value as string[]).join('、') : String(value ?? '')
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  level.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openDetail(id: unknown) {
  void router.push({ name: 'flood-detail', params: { id: String(id) } })
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (status.value) query.set('status', status.value)
  if (level.value) query.set('level', level.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('防汛记录列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const levelRank = (v: unknown) => levels.indexOf(String(v))
    stats.value = [
      { label: '在警事件', value: rows.value.filter((r) => ['待响应', '响应中'].includes(String(r.status))).length },
      { label: '橙色及以上', value: rows.value.filter((r) => levelRank(r['预警级别']) >= 2).length },
      { label: '当前页记录', value: rows.value.length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '防汛应急列表读取失败'
  }
}

onMounted(reload)
</script>
