<script setup>
import { ref, useTemplateRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/js/http/api.js'

const route = useRoute()
const router = useRouter()
const dialog = useTemplateRef('dialog')
const character = ref(null)
const groups = ref([])
const selected = ref('new')
const name = ref('')
const error = ref('')
const busy = ref(false)

async function open(value) {
  if (busy.value) return
  character.value = value
  name.value = `与${value.name}的群聊`.slice(0, 50)
  selected.value = 'new'
  error.value = ''
  groups.value = []
  busy.value = true
  dialog.value.showModal()
  try {
    const { data } = await api.get('/api/groups/', { timeout: 8000 })
    groups.value = data.groups
    if (data.groups.some(group => String(group.id) === route.query.group_id)) selected.value = route.query.group_id
    else if (data.groups.length) selected.value = String(data.groups[0].id)
  } catch {
    error.value = '无法获取群聊，请稍后重新打开'
  } finally {
    busy.value = false
  }
}

async function invite() {
  if (busy.value || (selected.value === 'new' && !name.value.trim())) return
  busy.value = true
  error.value = ''
  const characterId = character.value.id
  try {
    let id = selected.value
    if (id === 'new') {
      const { data } = await api.post('/api/groups/', { name: name.value.trim() })
      id = data.group.id
      selected.value = String(id)
      groups.value.unshift(data.group)
    }
    await api.post(`/api/groups/${id}/characters/`, { character_id: characterId })
    dialog.value.close()
    await router.push({ name: 'group-index', params: { group_id: id } })
  } catch (err) {
    error.value = err.response?.data?.result || '邀请失败，请重试'
  } finally {
    busy.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <dialog ref="dialog" class="modal">
    <form class="modal-box max-w-md rounded-2xl" @submit.prevent="invite">
      <h2 class="text-xl font-bold">邀请 {{ character?.name }} 加入群聊</h2>
      <label class="block mt-5 mb-2" for="invite-group">选择群聊</label>
      <select id="invite-group" v-model="selected" class="select w-full rounded-2xl" :disabled="busy">
        <option value="new">新建群聊</option>
        <option v-for="group in groups" :key="group.id" :value="String(group.id)">{{ group.name }}</option>
      </select>
      <label v-if="selected === 'new'" class="block mt-4">
        群聊名称
        <input v-model="name" class="input w-full mt-2 rounded-2xl" maxlength="50" :disabled="busy" required />
      </label>
      <p v-if="error" class="text-error mt-3" role="alert">{{ error }}</p>
      <div class="modal-action">
        <button type="button" class="btn btn-ghost rounded-full" :disabled="busy" @click="dialog.close()">取消</button>
        <button class="btn btn-success rounded-full" :disabled="busy || (selected === 'new' && !name.trim())">{{ busy ? '处理中…' : '邀请并进入群聊' }}</button>
      </div>
    </form>
  </dialog>
</template>
