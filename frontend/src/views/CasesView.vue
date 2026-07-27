<!-- 案例列表页：展示所有数字员工列表，点击进入详情 -->
<template>
  <div class="cases-page">
    <div class="page-header">
      <h1 class="page-title">数字员工案例</h1>
      <p class="page-desc">探索各岗位数字员工的能力与应用场景</p>
    </div>
    <div class="case-grid">
      <div v-for="emp in employees" :key="emp.id" class="case-card card-hover" @click="goDetail(emp.id)">
        <div class="case-avatar" :style="{ background: empGradient(emp.id) }">{{ (emp.name || emp.id).charAt(0) }}</div>
        <div class="case-info">
          <div class="case-name">{{ emp.name }}</div>
          <div class="case-role">{{ emp.role }}</div>
          <div class="case-tags">
            <span class="case-tag" v-for="sk in (emp.skills || []).slice(0, 3)" :key="sk">{{ sk }}</span>
          </div>
        </div>
        <div class="case-arrow">→</div>
      </div>
      <div v-if="!employees.length && !loading" class="empty-hint">暂无案例数据</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api.js'

defineOptions({ name: 'CasesView' })
const router = useRouter()
const employees = ref([])
const loading = ref(true)

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) { return gradients[(id?.charCodeAt(0) || 0) % gradients.length] }

onMounted(async () => {
  try {
    const { data } = await api.get('/employees')
    employees.value = data || []
  } catch {} finally { loading.value = false }
})

function goDetail(id) { router.push({ name: 'case-detail', params: { id } }) }
</script>

<style scoped>
.cases-page { padding: 32px 40px 64px; min-width: 1000px; }
.page-header { margin-bottom: 32px; }
.page-title { font-size: 24px; font-weight: 700; color: #0f172a; }
.page-desc { font-size: 14px; color: #64748b; margin-top: 6px; }
.case-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.case-card {
  display: flex; align-items: center; gap: 18px;
  padding: 20px 24px; background: #fff; border: 1px solid #e2e8f0;
  border-radius: 14px; cursor: pointer; transition: all 0.2s;
}
.case-card:hover { border-color: #3b82f6; box-shadow: 0 2px 12px rgba(59,130,246,0.08); transform: translateY(-1px); }
.case-avatar {
  width: 56px; height: 56px; border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; font-weight: 700; color: #fff; flex-shrink: 0;
}
.case-info { flex: 1; min-width: 0; }
.case-name { font-size: 16px; font-weight: 600; color: #0f172a; }
.case-role { font-size: 13px; color: #64748b; margin-top: 2px; }
.case-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.case-tag { font-size: 11px; background: #f1f5f9; color: #475569; padding: 2px 8px; border-radius: 6px; }
.case-arrow { font-size: 18px; color: #94a3b8; flex-shrink: 0; }
.empty-hint { padding: 40px; text-align: center; color: #94a3b8; font-size: 14px; }
</style>