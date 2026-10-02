<template>
  <div v-if="store.hasNotices" class="notice-bar" :class="topClass">
    <div class="notice-main" @click="openTop">
      <span class="notice-badge">防汛通知</span>
      <strong>{{ store.top?.标题 }}</strong>
      <span class="notice-roads">影响路段：{{ store.top?.影响路段 }}</span>
      <span class="notice-meta">{{ store.top?.状态 }} · 更新 {{ store.top?.updated_at }}</span>
    </div>
    <div class="notice-list">
      <RouterLink
        v-for="item in store.items"
        :key="item.event_id"
        :to="`/flood/${item.event_id}`"
        class="notice-chip"
        :class="levelClass(item.级别)"
      >
        {{ item.记录编号 }} · {{ item.级别 }}
      </RouterLink>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import { levelClass, useNoticeStore } from '@/stores/notice'

const store = useNoticeStore()
const router = useRouter()
const topClass = computed(() => (store.top ? levelClass(store.top.级别) : ''))

function openTop() {
  if (store.top) void router.push(`/flood/${store.top.event_id}`)
}

onMounted(() => store.start())
</script>
