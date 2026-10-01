<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">市政道路桥梁养护管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <FloodNoticeBar ref="noticeBar" @open="openEvent" @workbench="openWorkbench" />
        <span class="head-user">当前值班：{{ store.operator }} · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import FloodNoticeBar from '@/components/FloodNoticeBar.vue'
import { floodBus } from '@/stores/floodBus'
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()
const router = useRouter()
const noticeBar = ref<InstanceType<typeof FloodNoticeBar> | null>(null)

const navItems = [{ label: "运营概览", path: "/" }, { label: "路段管理", path: "/road_section" }, { label: "日常巡查", path: "/patrol" }, { label: "路面病害", path: "/pavement" }, { label: "桥梁定检", path: "/bridge" }, { label: "桥梁档案", path: "/bridge_info" }, { label: "隧道管养", path: "/tunnel" }, { label: "交安设施", path: "/traffic_facility" }, { label: "排水设施", path: "/drainage" }, { label: "绿化管养", path: "/green" }, { label: "路灯照明", path: "/lighting" }, { label: "除雪防滑", path: "/winter" }, { label: "防汛应急", path: "/flood" }, { label: "道路风险工作台", path: "/road-risk" }, { label: "边坡防护", path: "/slope" }, { label: "伸缩缝管理", path: "/expansion" }, { label: "支座维护", path: "/bearing" }, { label: "养护工程", path: "/project" }, { label: "养护车辆", path: "/vehicle" }, { label: "养护材料", path: "/material" }]

function openEvent(eventId: number) {
  void router.push({ name: 'flood-detail', params: { id: eventId } })
}

function openWorkbench() {
  void router.push({ name: 'road-risk' })
}

function refreshNotice() {
  void noticeBar.value?.reload()
}

watch(() => floodBus.noticeTick, () => refreshNotice())
</script>
