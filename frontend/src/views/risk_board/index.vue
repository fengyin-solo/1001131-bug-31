<template>
  <section class="page" data-module="risk-board">
    <header class="page-head">
      <div>
        <h2>道路风险工作台</h2>
        <p class="page-desc">按防汛预警事件汇总道路风险面与排水任务待办；升级发布后这里与通知栏、防汛档案同事务刷新，多起事件覆盖同一路段时取最高级别。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新工作台</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">风险路段</span>
        <strong class="stat-value">{{ board.stats?.['风险路段'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待办排水任务</span>
        <strong class="stat-value">{{ board.stats?.['待办排水任务'] ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">生效预警事件</span>
        <strong class="stat-value">{{ board.stats?.['生效预警事件'] ?? 0 }}</strong>
      </article>
      <article v-for="(count, level) in board.stats?.['级别分布'] ?? {}" :key="level" class="stat-card">
        <span class="stat-label">{{ level }}</span>
        <strong class="stat-value">{{ count }}</strong>
      </article>
    </div>

    <h3 style="font-size: 15px">道路风险面</h3>
    <table class="data-table" style="margin-bottom: 16px">
      <thead>
        <tr>
          <th v-for="column in roadColumns" :key="column">{{ column }}</th>
          <th>防汛记录</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in board.roads" :key="row['路段编号']">
          <td>{{ row['路段编号'] }}</td>
          <td>{{ row['路段名称'] }}</td>
          <td>{{ row['起止桩号'] }}</td>
          <td>
            <span class="level-tag" :class="row['风险等级'] === '无' ? 'level-idle' : levelClass(String(row['风险等级']))">
              {{ row['风险等级'] }}
            </span>
          </td>
          <td>{{ row['风险面状态'] }}</td>
          <td>{{ row['排水设施数'] }}</td>
          <td>{{ row['待办排水任务'] }}</td>
          <td>
            <RouterLink v-if="row['关联防汛记录']" class="link" :to="`/flood/${recordIdMap[String(row['关联防汛记录'])] ?? ''}`">
              {{ row['关联防汛记录'] }}
            </RouterLink>
            <span v-else>—</span>
          </td>
        </tr>
        <tr v-if="!board.roads?.length">
          <td :colspan="roadColumns.length + 1" class="empty-state">暂无管养路段数据</td>
        </tr>
      </tbody>
    </table>

    <h3 style="font-size: 15px">排水任务（投影自生效预警）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in taskColumns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in board.drain_tasks" :key="task['设施编号']">
          <td>{{ task['设施编号'] }}</td>
          <td>{{ task['所属路段'] }}</td>
          <td>{{ task['设施类型'] }}</td>
          <td>
            <span class="level-tag" :class="levelClass(String(task['预警级别']))">{{ task['预警级别'] }}</span>
          </td>
          <td>{{ task['排水任务状态'] }}</td>
          <td>
            <RouterLink class="link" :to="`/flood/${recordIdMap[String(task['关联防汛记录'])] ?? ''}`">{{ task['关联防汛记录'] }}</RouterLink>
          </td>
        </tr>
        <tr v-if="!board.drain_tasks?.length">
          <td :colspan="taskColumns.length" class="empty-state">当前无生效预警派生的排水任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'
import { levelClass } from '@/stores/notice'

type Board = {
  roads: Record<string, string | number>[]
  drain_tasks: Record<string, string>[]
  stats?: {
    风险路段: number
    待办排水任务: number
    生效预警事件: number
    级别分布: Record<string, number>
  }
}

const roadColumns = ['路段编号', '路段名称', '起止桩号', '风险等级', '风险面状态', '排水设施数', '待办排水任务']
const taskColumns = ['设施编号', '所属路段', '设施类型', '预警级别', '排水任务状态', '关联防汛记录']

const board = ref<Board>({ roads: [], drain_tasks: [] })
const recordIdMap = ref<Record<string, string | number>>({})
const errorMessage = ref('')

async function reload() {
  errorMessage.value = ''
  try {
    const [boardResp, floodResp] = await Promise.all([
      request('/api/flood/risk-board'),
      request('/api/flood?size=200'),
    ])
    if (!boardResp.ok) throw new Error('道路风险工作台读取失败')
    board.value = await boardResp.json()
    if (floodResp.ok) {
      const payload = await floodResp.json()
      recordIdMap.value = Object.fromEntries(
        (payload.items ?? []).map((row: Record<string, any>) => [String(row['记录编号']), row.id]),
      )
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路风险工作台读取失败'
  }
}

onMounted(reload)
</script>
