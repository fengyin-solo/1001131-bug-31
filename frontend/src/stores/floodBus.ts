/** 防汛链路事件总线：升级/结束后通知通知栏与各工作台刷新，避免跨页面层层透传。 */
import { reactive } from 'vue'

export const floodBus = reactive({
  noticeTick: 0,
  lastEventId: null as number | null,
})

export function notifyFloodChanged(eventId?: number) {
  floodBus.lastEventId = eventId ?? null
  floodBus.noticeTick += 1
}
