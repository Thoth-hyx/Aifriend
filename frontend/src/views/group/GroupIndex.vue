<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/js/http/api.js'
import { useGroupStore } from '@/stores/group.js'

const route = useRoute()
const router = useRouter()
const store = useGroupStore()
const activeId = computed(() => Number(route.params.group_id) || null)
const activeGroup = computed(() => store.groups.find(group => group.id === activeId.value))
const state = computed(() => activeId.value ? store.session(activeId.value) : null)
const scroll = useTemplateRef('scroll')
const createDialog = useTemplateRef('create-dialog')
const name = ref('')
const pageError = ref('')
const createError = ref('')
const creating = ref(false)
const retrying = ref(null)
const loading = ref(true)
let timer = null
let stopped = false
let lastListSync = 0
let stickToBottom = true

const statusLabel = { sending: '发送中', pending: '等待回复', generating: '正在回复', failed: '失败' }

async function refreshGroups() {
  try {
    if (!await store.loadGroups()) return
    if (stopped) return
    pageError.value = ''
    lastListSync = Date.now()
    loading.value = false
    if (!activeId.value && store.groups.length) {
      await router.replace({ name: 'group-index', params: { group_id: store.groups[0].id } })
    }
  } catch (error) {
    pageError.value = store.errorText(error)
    loading.value = false
  }
}

// ponytail: incremental polling, ~1s active and ~5s for the list; switch to push if latency/load requires it.
async function poll() {
  if (stopped) return
  if (Date.now() - lastListSync > 5000) await refreshGroups()
  if (!stopped && activeId.value) await store.sync(activeId.value)
  if (!stopped) timer = setTimeout(poll, 1000)
}

watch(activeId, async (id) => {
  if (!id) return
  stickToBottom = store.session(id).scrollTop === null
  await store.sync(id)
  if (activeId.value !== id || stopped) return
  await nextTick()
  if (scroll.value) scroll.value.scrollTop = state.value.scrollTop ?? scroll.value.scrollHeight
  rememberScroll()
}, { immediate: true })

watch(() => state.value?.messages.map(message => `${message.id}:${message.revision}:${message.status}`).join('|'), async () => {
  const id = activeId.value
  await nextTick()
  if (id === activeId.value && stickToBottom && scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight
})

function rememberScroll() {
  if (!scroll.value || !state.value) return
  state.value.scrollTop = scroll.value.scrollTop
  stickToBottom = scroll.value.scrollHeight - scroll.value.scrollTop - scroll.value.clientHeight < 80
}

async function createGroup() {
  if (creating.value || !name.value.trim()) return
  creating.value = true
  createError.value = ''
  try {
    const { data } = await api.post('/api/groups/', { name: name.value.trim() })
    if (stopped) return
    createDialog.value.close()
    name.value = ''
    await store.loadGroups()
    await router.push({ name: 'group-index', params: { group_id: data.group.id } })
  } catch (error) {
    createError.value = store.errorText(error)
  } finally {
    creating.value = false
  }
}

async function send() {
  if (!state.value || state.value.sending || !state.value.draft.trim()) return
  const id = activeId.value
  const content = state.value.draft.trim()
  const target = state.value.target ? Number(state.value.target) : null
  state.value.draft = ''
  stickToBottom = true
  await store.send(id, content, target)
}

async function retry(message) {
  const id = activeId.value
  if (retrying.value !== null) return
  retrying.value = message.id
  try {
    await store.retry(id, message)
  } catch (error) {
    pageError.value = store.errorText(error)
  } finally {
    retrying.value = null
  }
}

function resume() {
  if (!stopped) {
    lastListSync = 0
    if (activeId.value) store.sync(activeId.value)
  }
}

onMounted(() => {
  poll()
  window.addEventListener('online', resume)
  document.addEventListener('visibilitychange', resume)
})

onBeforeUnmount(() => {
  stopped = true
  clearTimeout(timer)
  window.removeEventListener('online', resume)
  document.removeEventListener('visibilitychange', resume)
})
</script>

<template>
  <div class="flex flex-col md:flex-row h-[calc(100dvh-4rem)] min-h-120 bg-base-100">
    <aside class="w-full md:w-72 shrink-0 border-b md:border-b-0 md:border-r border-base-300 flex flex-col max-h-56 md:max-h-none">
      <div class="flex items-center justify-between p-4">
        <h1 class="text-xl font-bold">AI 群聊</h1>
        <button class="btn btn-primary btn-sm" @click="createError = ''; createDialog.showModal()">新建</button>
      </div>
      <div class="overflow-y-auto flex-1 px-2 pb-2">
        <p v-if="loading" class="text-base-content/60 p-3">加载会话中…</p>
        <p v-else-if="!store.groups.length" class="text-base-content/60 p-3 text-sm">创建群聊，再从好友页面邀请 AI 角色。</p>
        <RouterLink v-for="group in store.groups" :key="group.id" :to="{ name: 'group-index', params: { group_id: group.id } }"
          class="block rounded-xl p-3 mb-1 hover:bg-base-200" :class="{ 'bg-base-200': activeId === group.id }">
          <div class="flex items-center justify-between gap-2">
            <span class="font-semibold truncate">{{ group.name }}</span>
            <span class="badge badge-sm shrink-0">{{ group.characters.length }} 个角色</span>
          </div>
          <p class="text-xs text-base-content/60 truncate mt-2">
            {{ group.latest_message ? `${group.latest_message.sender_name}：${group.latest_message.content || statusLabel[group.latest_message.status] || '暂无内容'}` : '暂无消息' }}
          </p>
        </RouterLink>
      </div>
    </aside>

    <main class="min-w-0 flex-1 flex flex-col min-h-0">
      <p v-if="pageError" class="bg-error/10 text-error px-4 py-2 text-sm" role="alert">{{ pageError }}</p>
      <template v-if="activeGroup && state">
        <header class="p-4 border-b border-base-300 flex items-center justify-between gap-3">
          <div class="min-w-0">
            <h2 class="font-bold text-lg truncate">{{ activeGroup.name }}</h2>
            <p class="text-xs mt-1" :class="state.connected ? 'text-success' : 'text-warning'" role="status">
              {{ state.connected ? '消息已同步' : '正在连接 / 恢复消息…' }}
            </p>
          </div>
          <RouterLink class="btn btn-outline btn-sm shrink-0" :to="{ name: 'friend-index', query: { group_id: activeId } }">邀请角色</RouterLink>
        </header>
        <div v-if="activeGroup.characters.length" class="px-4 py-2 border-b border-base-300 flex flex-wrap gap-2">
          <div v-for="character in activeGroup.characters" :key="character.id" class="flex items-center gap-1.5 text-xs bg-base-200 rounded-full py-1 px-2">
            <img :src="character.photo" alt="" class="w-5 h-5 rounded-full object-cover" />{{ character.name }}
          </div>
        </div>
        <p v-if="state.error" class="bg-warning/10 text-warning px-4 py-2 text-sm" role="alert">{{ state.error }}</p>
        <div ref="scroll" class="flex-1 min-h-0 overflow-y-auto p-4 md:p-6" @scroll="rememberScroll">
          <div v-if="!state.messages.length" class="h-full flex flex-col items-center justify-center text-base-content/60 gap-3">
            <p>{{ activeGroup.characters.length ? '发一条消息，开始和 AI 角色交流' : '群聊已创建，先邀请 AI 角色加入' }}</p>
            <RouterLink v-if="!activeGroup.characters.length" class="btn btn-primary btn-sm" :to="{ name: 'friend-index', query: { group_id: activeId } }">去好友页选择角色</RouterLink>
          </div>
          <div v-for="message in state.messages" :key="message.id" class="chat" :class="message.role === 'user' ? 'chat-end' : 'chat-start'">
            <div class="chat-header mb-1 text-base-content/70">{{ message.sender_name }}</div>
            <div class="chat-bubble whitespace-pre-wrap break-words max-w-[90%] md:max-w-[75%]" :class="message.role === 'user' ? 'chat-bubble-primary' : 'bg-base-200 text-base-content'">
              {{ message.content || statusLabel[message.status] || '…' }}
            </div>
            <div class="chat-footer mt-1 flex items-center gap-2 text-xs">
              <span v-if="message.status !== 'completed'" :class="{ 'text-error': message.status === 'failed' }">{{ message.error || statusLabel[message.status] }}</span>
              <span v-else>{{ message.role === 'user' ? '已发送' : '回复完成' }}</span>
              <button v-if="message.status === 'failed'" class="link text-error" :disabled="retrying !== null || state.sending" @click="retry(message)">{{ retrying === message.id ? '重试中…' : '重试' }}</button>
            </div>
          </div>
        </div>
        <form class="p-4 border-t border-base-300 bg-base-100" @submit.prevent="send">
          <label class="flex items-center gap-2 text-sm mb-3">
            回复角色
            <select v-model="state.target" class="select select-sm w-auto max-w-56" aria-label="选择回复角色">
              <option value="">随机一个角色</option>
              <option v-for="character in activeGroup.characters" :key="character.id" :value="String(character.id)">{{ character.name }}</option>
            </select>
          </label>
          <div class="flex gap-2 items-end">
            <textarea v-model="state.draft" class="textarea flex-1 resize-none" rows="2" maxlength="2000" placeholder="输入消息，Enter 发送，Shift+Enter 换行" aria-label="群聊消息"
              :disabled="!activeGroup.characters.length" @keydown.enter="event => { if (!event.shiftKey && !event.isComposing) { event.preventDefault(); send() } }"></textarea>
            <button class="btn btn-primary" :disabled="state.sending || !state.draft.trim() || !activeGroup.characters.length">{{ state.sending ? '发送中' : '发送' }}</button>
          </div>
          <p class="text-xs text-base-content/50 mt-2">未指定角色时随机回复；切换会话后 AI 会继续生成。</p>
        </form>
      </template>
      <div v-else class="flex-1 flex items-center justify-center text-base-content/60">
        {{ activeId && !loading ? '群聊不存在或无权访问' : '选择一个会话，或新建 AI 群聊' }}
      </div>
    </main>

    <dialog ref="create-dialog" class="modal">
      <form class="modal-box max-w-md" @submit.prevent="createGroup">
        <h2 class="text-xl font-bold">新建 AI 群聊</h2>
        <label class="block mt-4" for="group-name">群聊名称</label>
        <input id="group-name" v-model="name" class="input w-full mt-2" maxlength="50" required :disabled="creating" placeholder="例如：我的 AI 讨论室" />
        <p v-if="createError" class="text-error mt-3" role="alert">{{ createError }}</p>
        <div class="modal-action">
          <button type="button" class="btn btn-ghost" :disabled="creating" @click="createDialog.close()">取消</button>
          <button class="btn btn-primary" :disabled="creating || !name.trim()">{{ creating ? '创建中…' : '创建' }}</button>
        </div>
      </form>
    </dialog>
  </div>
</template>
