import { defineStore } from 'pinia'

import { request } from '@/api/client'

export type FloodNotice = {
  event_id: number
  记录编号: string
  级别: string
  级别序: number
  标题: string
  影响路段: string
  状态: string
  updated_at: string
}

type NoticePayload = { items: FloodNotice[]; total: number; top: FloodNotice | null }

const LEVEL_CLASS: Record<string, string> = {
  蓝色预警: 'notice-blue',
  黄色预警: 'notice-yellow',
  橙色预警: 'notice-orange',
  红色预警: 'notice-red',
}

export function levelClass(level: string): string {
  return LEVEL_CLASS[level] ?? ''
}

export const useNoticeStore = defineStore('flood-notice', {
  state: () => ({
    items: [] as FloodNotice[],
    timer: 0 as ReturnType<typeof setInterval> | 0,
  }),
  getters: {
    top(state): FloodNotice | null {
      if (!state.items.length) return null
      return state.items.reduce((best, item) => (item.级别序 > best.级别序 ? item : best), state.items[0])
    },
    hasNotices(state): boolean {
      return state.items.length > 0
    },
  },
  actions: {
    async refresh() {
      try {
        const response = await request('/api/flood/notices/active')
        if (!response.ok) return
        const payload = (await response.json()) as NoticePayload
        // 按事件 id 对齐替换，避免重复点击时列表里出现同一个事件两次
        const incoming = new Map(payload.items.map((item) => [item.event_id, item]))
        this.items = this.items
          .filter((item) => incoming.has(item.event_id))
          .map((item) => incoming.get(item.event_id) ?? item)
        for (const item of payload.items) {
          if (!this.items.some((row) => row.event_id === item.event_id)) this.items.push(item)
        }
      } catch {
        // 通知栏轮询静默失败，不打断值守操作
      }
    },
    start() {
      if (this.timer) return
      void this.refresh()
      this.timer = setInterval(() => void this.refresh(), 15000)
    },
  },
})
