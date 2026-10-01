<template>
  <div v-if="notices.length" class="notice-bar" data-module="flood-notice">
    <span class="notice-title">防汛通知栏</span>
    <article
      v-for="notice in notices"
      :key="String(notice.事件id)"
      class="notice-chip"
      :class="levelClass(notice.级别)"
      @click="$emit('open', notice.事件id)"
    >
      <span class="notice-level">{{ notice.级别 }}</span>
      <span class="notice-record">{{ notice.记录编号 }}</span>
      <span class="notice-sections">{{ sectionText(notice.影响路段) }}</span>
      <span class="notice-time">{{ notice.更新时间 }}</span>
    </article>
    <button v-if="!compact" class="link notice-more" type="button" @click="$emit('workbench')">
      道路风险工作台 →
    </button>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { fetchJson } from '@/api/client'
import { floodBus } from '@/stores/floodBus'

type Notice = {
  事件id: number
  记录编号: string
  级别: string
  影响路段: string[] | string
  更新时间: string
}

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })
defineEmits<{
  (e: 'open', eventId: number): void
  (e: 'workbench'): void
}>()

const notices = ref<Notice[]>([])

function levelClass(level: string): string {
  return {
    蓝色预警: 'lv-blue',
    黄色预警: 'lv-yellow',
    橙色预警: 'lv-orange',
    红色预警: 'lv-red',
  }[level] ?? 'lv-blue'
}

function sectionText(value: string[] | string): string {
  return Array.isArray(value) ? value.join('、') : String(value ?? '')
}

async function reload() {
  try {
    const payload = await fetchJson<{ items: Notice[] }>('/api/flood/notifications/active')
    notices.value = payload.items ?? []
  } catch {
    notices.value = []
  }
}

onMounted(reload)
watch(() => floodBus.noticeTick, () => reload())
defineExpose({ reload })
</script>
