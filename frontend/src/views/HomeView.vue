<!-- 平台首页：欢迎横幅、统计卡片、快捷入口、数字员工列表 -->
<template>
  <div class="home-page">
    <!-- 顶部欢迎横幅 -->
    <div class="hero-section">
      <div class="hero-content">
        <h1 class="hero-title">
          欢迎回来，<span class="gradient-text">{{ auth.username }}</span>
        </h1>
        <p class="hero-sub">UniEmployee 企业级数字员工平台 — 让 AI 成为你的数字劳动力</p>
      </div>
      <div class="hero-actions">
        <n-button type="primary" @click="router.push({name:'chat'})" class="start-btn">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
          开始对话
        </n-button>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div v-for="s in stats" :key="s.label" class="stat-card card card-hover">
        <div class="stat-icon" :style="{ background: s.color }">{{ s.icon }}</div>
        <div class="stat-body">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="quick-grid">
      <div class="quick-card card card-hover" @click="router.push({name:'chat'})">
        <div class="quick-icon" style="background:linear-gradient(135deg,#3b82f6,#2563eb)">💬</div>
        <div class="quick-info">
          <div class="quick-label">对话工作台</div>
          <div class="quick-desc">与你的数字员工交流</div>
        </div>
      </div>
      <div class="quick-card card card-hover" @click="router.push({name:'history'})">
        <div class="quick-icon" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9)">🕘</div>
        <div class="quick-info">
          <div class="quick-label">会话历史</div>
          <div class="quick-desc">查看过往对话记录</div>
        </div>
      </div>
      <div v-if="auth.isAdmin" class="quick-card card card-hover" @click="router.push({name:'admin'})">
        <div class="quick-icon" style="background:linear-gradient(135deg,#10b981,#047857)">👥</div>
        <div class="quick-info">
          <div class="quick-label">员工管理</div>
          <div class="quick-desc">配置数字员工</div>
        </div>
      </div>
      <div class="quick-card card card-hover" @click="router.push({name:'resources'})">
        <div class="quick-icon" style="background:linear-gradient(135deg,#f59e0b,#b45309)">📚</div>
        <div class="quick-info">
          <div class="quick-label">资源中心</div>
          <div class="quick-desc">管理技能与知识库</div>
        </div>
      </div>
    </div>

    <!-- 数字员工 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">数字员工</h2>
        <n-button text type="primary" @click="router.push({name:'chat'})" class="section-more">查看全部 →</n-button>
      </div>
      <div class="emp-grid">
        <div
          v-for="emp in employees"
          :key="emp.id"
          class="emp-card card card-hover"
          @click="startChat(emp.id)"
        >
          <div class="emp-avatar" :style="{ background: empGradient(emp.id) }">
            {{ emp.name?.charAt(0) || '?' }}
          </div>
          <div class="emp-info">
            <div class="emp-name">{{ emp.name }}</div>
            <div class="emp-role">{{ emp.role }}</div>
            <div class="emp-status">
              <span class="status-dot"></span>
              在线
            </div>
          </div>
        </div>
        <div v-if="!employees.length && !loading" class="empty-hint">
          暂无已分配的数字员工
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

defineOptions({ name: 'HomeView' })

const router = useRouter()
const auth = useAuthStore()
const employees = ref([])
const loading = ref(true)

const stats = reactive([
  { icon: '👥', label: '数字员工', value: '—', color: 'rgba(59,130,246,0.10)' },
  { icon: '⚡', label: '技能', value: '—', color: 'rgba(16,185,129,0.10)' },
  { icon: '🔧', label: '工具', value: '—', color: 'rgba(139,92,246,0.10)' },
  { icon: '💬', label: '会话', value: '—', color: 'rgba(245,158,11,0.10)' },
])

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) {
  return gradients[(id?.charCodeAt(0) || 0) % gradients.length]
}

async function loadData() {
  try {
    const [catalogRes, empRes, convRes] = await Promise.all([
      api.get('/catalog'),
      api.get('/employees'),
      api.get('/conversations', { params: { limit: 0 } }),
    ])
    const cat = catalogRes.data
    const emps = empRes.data || []
    employees.value = Array.isArray(emps)
      ? emps.map(e => ({ id: e.id, ...e }))
      : []
    stats[0].value = employees.value.length
    stats[1].value = cat.skills?.length || 0
    stats[2].value = cat.tools?.length || 0
    const convData = convRes.data
    stats[3].value = Array.isArray(convData) ? convData.length : (convData?.total ?? 0)
  } catch {} finally { loading.value = false }
}

function startChat(empId) {
  router.push({ name: 'chat', query: { emp: empId } })
}

onMounted(loadData)
</script>

<style scoped>
.home-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 32px 64px;
}

/* 欢迎横幅 */
.hero-section {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 36px;
  gap: 24px;
}
.hero-title {
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 8px;
  line-height: 1.25;
}
.hero-sub {
  font-size: 14px;
  color: #64748b;
  line-height: 1.6;
}
.start-btn {
  height: 40px;
  padding: 0 24px !important;
  border-radius: 10px !important;
  font-weight: 600;
  font-size: 14px;
}

/* 统计卡片 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1;
}
.stat-label {
  font-size: 13px;
  color: #64748b;
  margin-top: 4px;
}

/* 快捷入口 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 40px;
}
.quick-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  cursor: pointer;
}
.quick-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.quick-label {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}
.quick-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

/* 分节标题 */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #0f172a;
}
.section-more {
  font-size: 13px;
}

/* 员工网格 */
.emp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.emp-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  cursor: pointer;
}
.emp-avatar {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.emp-name {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}
.emp-role {
  font-size: 13px;
  color: #64748b;
  margin-top: 2px;
}
.emp-status {
  font-size: 12px;
  color: #10b981;
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
</style>
