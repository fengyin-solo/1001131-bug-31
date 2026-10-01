<template>
  <section class="page" data-module="road-risk">
    <header class="page-head">
      <div>
        <h2>道路风险工作台</h2>
        <p class="page-desc">
          按影响路段汇总预警派生的道路风险面，取路段上最高风险；级别与管控状态随防汛升级同步对齐。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="reload">刷新风险面</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.cls">{{ item.value }}</strong>
      </article>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th>影响路段</th>
          <th>预警级别</th>
          <th>风险等级</th>
          <th>管控状态</th>
          <th>关联事件</th>
          <th>更新时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.影响路段">
          <td>{{ item.影响路段 }}</td>
          <td><span class="level-badge" :class="levelClass(String(item.预警级别))">{{ item.预警级别 }}</span></td>
          <td><span class="risk-tag" :class="levelClass(String(item.预警级别))">{{ item.风险等级 }}</span></td>
          <td>{{ item.管控状态 }}</td>
          <td>
            <button
              v-for="ref in item.关联事件"
              :key="String(ref.事件id)"
              class="link"
              type="button"
              @click="openEvent(ref.事件id)"
            >
              {{ ref.记录编号 }}·{{ ref.预警级别 }}
            </button>
          </td>
          <td>{{ item.更新时间 }}</td>
          <td>
            <button class="link" type="button" @click="openEvent(item.事件id)">处置链路</button>
          </td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="7" class="empty-state">当前没有受预警影响的路段风险面</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ items.length }} 个受影响路段</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { fetchJson } from '@/api/client'
import { floodBus } from '@/stores/floodBus'

type RiskItem = {
  事件id: number
  记录编号: string
  影响路段: string
  预警级别: string
  风险等级: string
  管控状态: string
  更新时间: string
  关联事件: Array<{ 事件id: number; 记录编号: string; 预警级别: string }>
}

const items = ref<RiskItem[]>([])
const errorMessage = ref('')
const router = useRouter()

const stats = ref([
  { label: '极高风险', value: 0, cls: 'lv-red' },
  { label: '高风险', value: 0, cls: 'lv-orange' },
  { label: '中风险', value: 0, cls: 'lv-yellow' },
  { label: '低风险', value: 0, cls: 'lv-blue' },
])

function levelClass(value: string): string {
  return {
    蓝色预警: 'lv-blue',
    黄色预警: 'lv-yellow',
    橙色预警: 'lv-orange',
    红色预警: 'lv-red',
  }[value] ?? 'lv-blue'
}

function openEvent(id: number) {
  void router.push({ name: 'flood-detail', params: { id: String(id) } })
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchJson<{ items: RiskItem[] }>('/api/road-risk/workbench')
    items.value = payload.items ?? []
    stats.value[0].value = items.value.filter((i) => i.风险等级 === '极高风险').length
    stats.value[1].value = items.value.filter((i) => i.风险等级 === '高风险').length
    stats.value[2].value = items.value.filter((i) => i.风险等级 === '中风险').length
    stats.value[3].value = items.value.filter((i) => i.风险等级 === '低风险').length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '道路风险工作台读取失败'
  }
}

onMounted(reload)
watch(() => floodBus.noticeTick, () => reload())
</script>
