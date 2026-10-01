<template>
  <section class="page" data-module="flood-detail">
    <header class="page-head">
      <div>
        <h2>防汛记录详情 <span class="page-desc">· {{ detail?.['记录编号'] }}</span></h2>
        <p class="page-desc">升级顺序固定：① 定位预警事件 → ② 核对影响路段 → ③ 发布升级。并发值守只推进一版。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="goBack">返回列表</button>
      </div>
    </header>

    <div v-if="detail" class="detail-grid">
      <article class="detail-card">
        <h3>① 预警事件</h3>
        <dl class="info-list">
          <div><dt>记录编号</dt><dd>{{ detail['记录编号'] }}</dd></div>
          <div><dt>当前级别</dt><dd><span class="level-badge" :class="levelClass(String(detail['预警级别']))">{{ detail['预警级别'] }}</span></dd></div>
          <div><dt>生效级别</dt><dd><span class="level-badge" :class="levelClass(String(detail['生效级别']))">{{ detail['生效级别'] }}</span></dd></div>
          <div><dt>影响路段</dt><dd>{{ sectionText(detail['影响路段']) }}</dd></div>
          <div><dt>积水深度</dt><dd>{{ detail['积水深度'] ?? '—' }}</dd></div>
          <div><dt>值守状态</dt><dd>{{ detail.status }}（版本 v{{ detail.version }}）</dd></div>
          <div><dt>来源口径</dt><dd>{{ detail['来源'] }}；自动监测建议 {{ detail['auto_level'] ?? '—' }}</dd></div>
          <div><dt>应急措施</dt><dd>{{ detail['应急措施'] ?? '—' }}</dd></div>
          <div><dt>投入人员</dt><dd>{{ detail['投入人员'] ?? '—' }}</dd></div>
        </dl>
        <p v-if="detail['迁移说明']" class="migration-note">迁移留痕：{{ detail['迁移说明'] }}</p>
      </article>

      <article class="detail-card">
        <h3>② 核对影响路段</h3>
        <p class="page-desc">交叉排水设施与管养路段台账，核对后领取发布凭证。</p>
        <button class="btn primary" type="button" :disabled="checking" @click="checkSections">
          {{ checking ? '核对中…' : '核对影响路段' }}
        </button>
        <table v-if="checked" class="data-table inner-table">
          <thead>
            <tr><th>影响路段</th><th>排水设施</th><th>管养路段</th><th>现任务</th><th>现风险</th><th>台账</th></tr>
          </thead>
          <tbody>
            <tr v-for="section in checked.sections" :key="section.影响路段">
              <td>{{ section.影响路段 }}</td>
              <td>
                <span v-for="f in section.排水设施" :key="f.设施编号" class="tag">{{ f.设施编号 }}·{{ f.设施状态 }}</span>
                <span v-if="!section.排水设施.length" class="muted">无</span>
              </td>
              <td>
                <span v-for="r in section.管养路段" :key="r.路段编号" class="tag">{{ r.路段编号 }}·{{ r.路段状态 }}</span>
                <span v-if="!section.管养路段.length" class="muted">无</span>
              </td>
              <td>{{ section.当前排水任务 ?? '—' }}</td>
              <td>{{ section.当前风险面 ?? '—' }}</td>
              <td :class="section.台账齐套 ? 'ok-text' : 'warn-text'">{{ section.台账齐套 ? '齐套' : '不齐' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="checked" class="ok-text">核对完成（版本 v{{ checked.version }}，{{ checked.checked_at }}），可发布升级。</p>
      </article>

      <article class="detail-card">
        <h3>③ 发布升级</h3>
        <p class="page-desc">只能升级到相邻节点；指挥部命令覆盖自动监测，通知与任务同事务提交。</p>
        <div class="level-ramp">
          <template v-for="(lv, idx) in levels" :key="lv">
            <button
              class="ramp-step"
              :class="[levelClass(lv), { active: lv === detail['生效级别'], next: idx === nextRank }]"
              type="button"
              :disabled="!canPublish || idx !== nextRank"
              @click="publish(lv)"
            >
              {{ lv }}
            </button>
            <span v-if="idx < levels.length - 1" class="ramp-arrow">→</span>
          </template>
        </div>
        <label class="filter-item remark-box">
          <span>命令说明（可选）</span>
          <input v-model="remark" placeholder="如：雨势加大，升级响应" />
        </label>
        <p v-if="!canPublish" class="muted">该事件状态为「{{ detail.status }}」，不接受新的升级命令。</p>
      </article>
    </div>

    <div v-else-if="errorMessage" class="empty-state">{{ errorMessage }}</div>

    <div v-if="detail" class="detail-grid two-col">
      <article class="detail-card">
        <h3>排水任务（随级别对齐）</h3>
        <table class="data-table">
          <thead><tr><th>影响路段</th><th>预警级别</th><th>任务状态</th><th>更新时间</th></tr></thead>
          <tbody>
            <tr v-for="task in detail['排水任务']" :key="String(task.id)">
              <td>{{ task.影响路段 }}</td>
              <td><span class="level-badge" :class="levelClass(String(task.预警级别))">{{ task.预警级别 }}</span></td>
              <td>{{ task.任务状态 }}</td>
              <td>{{ task.更新时间 }}</td>
            </tr>
            <tr v-if="!detail['排水任务'].length"><td colspan="4" class="empty-state">暂无派生任务</td></tr>
          </tbody>
        </table>
      </article>

      <article class="detail-card">
        <h3>道路风险面（随级别对齐）</h3>
        <table class="data-table">
          <thead><tr><th>影响路段</th><th>风险等级</th><th>管控状态</th><th>更新时间</th></tr></thead>
          <tbody>
            <tr v-for="risk in detail['道路风险面']" :key="String(risk.id)">
              <td>{{ risk.影响路段 }}</td>
              <td>{{ risk.风险等级 }}</td>
              <td>{{ risk.管控状态 }}</td>
              <td>{{ risk.更新时间 }}</td>
            </tr>
            <tr v-if="!detail['道路风险面'].length"><td colspan="4" class="empty-state">暂无风险面</td></tr>
          </tbody>
        </table>
      </article>
    </div>

    <article v-if="detail" class="detail-card">
      <h3>历史命令阶梯（每次命令留档）</h3>
      <table class="data-table">
        <thead><tr><th>序次</th><th>级别</th><th>来源</th><th>发布人</th><th>说明</th><th>发布时间</th></tr></thead>
        <tbody>
          <tr v-for="cmd in detail['历史命令']" :key="String(cmd.id)">
            <td>{{ cmd.序次 }}</td>
            <td><span class="level-badge" :class="levelClass(String(cmd.级别))">{{ cmd.级别 }}</span></td>
            <td>{{ cmd.来源 }}</td>
            <td>{{ cmd.发布人 }}</td>
            <td>{{ cmd.命令说明 }}</td>
            <td>{{ cmd.发布时间 }}</td>
          </tr>
          <tr v-if="!detail['历史命令'].length"><td colspan="6" class="empty-state">尚无指挥部命令，当前按自动监测口径生效</td></tr>
        </tbody>
      </table>
    </article>

    <footer class="page-foot">
      <span v-if="message" :class="publishing ? 'muted' : (lastOk ? 'ok-text' : 'error-text')">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'
import { notifyFloodChanged } from '@/stores/floodBus'

type Detail = Record<string, any>
type Checked = {
  version: number
  check_token: string
  checked_at: string
  sections: Array<Record<string, any>>
}

const levels = ['蓝色预警', '黄色预警', '橙色预警', '红色预警']
const route = useRoute()
const router = useRouter()

const detail = ref<Detail | null>(null)
const checked = ref<Checked | null>(null)
const checking = ref(false)
const publishing = ref(false)
const message = ref('')
const lastOk = ref(false)
const remark = ref('')
const errorMessage = ref('')

const eventId = computed(() => Number(route.params.id))
const currentRank = computed(() => levels.indexOf(String(detail.value?.['生效级别'] ?? '')))
const nextRank = computed(() => (currentRank.value >= 0 && currentRank.value < levels.length - 1 ? currentRank.value + 1 : -1))
const canPublish = computed(() => ['待响应', '响应中'].includes(String(detail.value?.status)))

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

function goBack() {
  void router.push({ name: 'flood' })
}

async function loadDetail() {
  errorMessage.value = ''
  try {
    const response = await request(`/api/flood/${eventId.value}`)
    if (!response.ok) throw new Error('防汛记录读取失败')
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '防汛记录读取失败'
  }
}

async function checkSections() {
  checking.value = true
  message.value = ''
  try {
    const response = await request(`/api/flood/${eventId.value}/check`, { method: 'POST', body: JSON.stringify({}) })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message ?? '核对失败')
    checked.value = payload.entry as Checked
    message.value = payload.message
    lastOk.value = true
  } catch (error) {
    message.value = error instanceof Error ? error.message : '核对失败'
    lastOk.value = false
  } finally {
    checking.value = false
  }
}

async function publish(targetLevel: string) {
  if (!checked.value) {
    message.value = '请先完成第②步：核对影响路段'
    lastOk.value = false
    return
  }
  publishing.value = true
  lastOk.value = false
  message.value = '正在事务内提交档案、通知与任务…'
  try {
    const response = await request(`/api/flood/${eventId.value}/escalate`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          target_level: targetLevel,
          check_token: checked.value.check_token,
          expected_version: checked.value.version,
          operator: '防汛值班员',
        },
        remark: remark.value || null,
      }),
    })
    const payload = await response.json()
    if (!payload.ok) throw new Error(payload.message ?? '升级失败')
    message.value = payload.message
    lastOk.value = true
    checked.value = null
    remark.value = ''
    notifyFloodChanged(eventId.value)
    await loadDetail()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '升级失败，已维持原级别'
    lastOk.value = false
  } finally {
    publishing.value = false
  }
}

onMounted(loadDetail)
</script>
