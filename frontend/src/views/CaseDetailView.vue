<!-- 案例详情页：单个数字员工的详细介绍（独立页面） -->
<template>
  <div class="detail-page">
    <nav class="nav">
      <div class="nav-inner">
        <a href="/" class="nav-logo">UniEmployee</a>
        <div class="nav-links">
          <a href="/">首页</a>
          <a href="/cases">案例</a>
          <a class="active">详情</a>
        </div>
      </div>
    </nav>

    <div class="detail-content">
      <div class="detail-back" @click="router.push({name:'cases'})">← 返回案例列表</div>
      <div v-if="!emp" class="empty-hint">员工不存在</div>
    <template v-else>
      <div class="detail-header">
        <div class="detail-avatar" :style="{ background: empGradient(emp.id) }">{{ (emp.name || emp.id).charAt(0) }}</div>
        <div>
          <div class="detail-name">{{ emp.name }}</div>
          <div class="detail-role">{{ emp.role }}</div>
        </div>
      </div>
      <div class="detail-section">
        <h3>技能配置</h3>
        <div class="detail-tags">
          <span class="detail-tag" v-for="sk in (emp.skills || [])" :key="sk">{{ sk }}</span>
          <span v-if="!emp.skills?.length" class="text-muted">暂未配置</span>
        </div>
      </div>
      <div class="detail-section">
        <h3>工具列表</h3>
        <div class="detail-tags">
          <span class="detail-tag tool-tag" v-for="t in (emp.tools || [])" :key="t">{{ t }}</span>
          <span v-if="!emp.tools?.length" class="text-muted">暂未配置</span>
        </div>
      </div>
      <div class="detail-section">
        <h3>说明</h3>
        <p class="text-muted">详细的能力介绍和典型案例正在完善中，敬请期待</p>
      </div>
    </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '../api.js'

defineOptions({ name: 'CaseDetailView' })
const router = useRouter()
const route = useRoute()
const emp = ref(null)

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) { return gradients[(id?.charCodeAt(0) || 0) % gradients.length] }

onMounted(async () => {
  try {
    const { data } = await api.get(`/admin/employees/${route.params.id}`)
    emp.value = data.error ? null : data
  } catch { emp.value = null }
})
</script>

<style scoped>
.detail-page { min-height: 100vh; background: #f8fafc; }
.nav {
  position: sticky; top: 0; z-index: 100; height: 64px;
  display: flex; align-items: center;
  background: rgba(255,255,255,0.95); backdrop-filter: blur(20px);
  border-bottom: 1px solid #e2e8f0;
}
.nav-inner { max-width: 1200px; margin: 0 auto; padding: 0 32px; width: 100%; display: flex; align-items: center; justify-content: space-between; }
.nav-logo { font-size: 18px; font-weight: 700; color: #0f172a; text-decoration: none; }
.nav-links { display: flex; gap: 32px; }
.nav-links a { font-size: 14px; color: #64748b; text-decoration: none; cursor: pointer; }
.nav-links a:hover, .nav-links a.active { color: #0f172a; font-weight: 500; }
.detail-content { max-width: 800px; margin: 0 auto; padding: 32px 32px 64px; }
.detail-back { font-size: 13px; color: #3b82f6; cursor: pointer; margin-bottom: 24px; display: inline-block; }
.detail-back:hover { text-decoration: underline; }
.detail-header { display: flex; align-items: center; gap: 20px; margin-bottom: 32px; }
.detail-avatar { width: 64px; height: 64px; border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 26px; font-weight: 700; color: #fff; flex-shrink: 0; }
.detail-name { font-size: 22px; font-weight: 700; color: #0f172a; }
.detail-role { font-size: 14px; color: #64748b; margin-top: 4px; }
.detail-section { margin-bottom: 28px; }
.detail-section h3 { font-size: 15px; font-weight: 600; color: #334155; margin-bottom: 12px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.detail-tag { font-size: 12px; background: #eff6ff; color: #2563eb; padding: 4px 10px; border-radius: 8px; }
.tool-tag { background: #f0fdf4; color: #16a34a; }
.text-muted { font-size: 13px; color: #94a3b8; }
.empty-hint { padding: 40px; text-align: center; color: #94a3b8; font-size: 14px; }
</style>