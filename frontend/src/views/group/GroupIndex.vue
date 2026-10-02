<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/js/http/api.js'
import { useGroupStore } from '@/stores/group.js'
import { useUserStore } from '@/stores/user.js'
import GroupIcon from '@/components/navbar/icons/GroupIcon.vue'
import SendIcon from '@/components/character/icons/SendIcon.vue'
import { replyBubbles } from '@/js/replyMessages.js'

const route = useRoute()
const router = useRouter()
const store = useGroupStore()
const user = useUserStore()
const activeId = computed(() => Number(route.params.group_id) || null)
const activeGroup = computed(() => store.groups.find(group => group.id === activeId.value))
const state = computed(() => activeId.value ? store.session(activeId.value) : null)
const bubbles = computed(() => (state.value?.messages || []).flatMap(replyBubbles))
const scroll = useTemplateRef('scroll')
const createDialog = useTemplateRef('create-dialog')
const membersDialog = useTemplateRef('members-dialog')
const removeCandidate = ref(null)
const removing = ref(false)
const memberError = ref('')
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
    if (stopped || route.name !== 'group-index') return
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
  membersDialog.value?.close()
  removeCandidate.value = null
  memberError.value = ''
  if (!id) return
  stickToBottom = store.session(id).scrollTop === null
  await store.sync(id)
  if (activeId.value !== id || stopped) return
  await nextTick()
  if (scroll.value) scroll.value.scrollTop = state.value.scrollTop ?? scroll.value.scrollHeight
  rememberScroll()
}, { immediate: true })

watch(() => activeGroup.value?.characters.map(character => character.id).join(','), () => {
  if (state.value?.target && !activeGroup.value?.characters.some(character => character.id === Number(state.value.target))) {
    state.value.target = ''
  }
  if (removeCandidate.value && !activeGroup.value?.characters.some(character => character.id === removeCandidate.value.id)) {
    removeCandidate.value = null
  }
})

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

function messagePhoto(message) {
  return message.role === 'user' ? user.photo : message.sender_photo
}

function canRetry(message) {
  return message.role === 'user' || activeGroup.value?.characters.some(character => character.id === message.character_id)
}

function openMembers() {
  removeCandidate.value = null
  memberError.value = ''
  membersDialog.value.showModal()
}

async function removeMember() {
  if (!removeCandidate.value || removing.value) return
  const id = activeId.value
  const characterId = removeCandidate.value.id
  removing.value = true
  memberError.value = ''
  try {
    await store.removeCharacter(id, characterId)
    if (id === activeId.value) removeCandidate.value = null
  } catch (error) {
    if (id === activeId.value) memberError.value = store.errorText(error)
  } finally {
    removing.value = false
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
  <div class="mx-3 my-3 flex h-[calc(100dvh-5.5rem)] flex-col overflow-hidden rounded-2xl border border-base-200 bg-base-100 shadow-sm md:mx-9 md:my-8 md:h-[calc(100dvh-8rem)] md:flex-row">
    <aside class="flex max-h-44 w-full shrink-0 flex-col border-b border-base-200 bg-base-200/40 md:max-h-none md:w-64 md:border-r md:border-b-0">
      <div class="flex items-center justify-between gap-2 p-4">
        <h1 class="flex items-center gap-2 text-lg font-bold"><GroupIcon />群聊</h1>
        <button class="btn btn-sm rounded-full" @click="createError = ''; createDialog.showModal()">＋ 新建</button>
      </div>
      <div class="flex-1 overflow-y-auto px-2 pb-2">
        <p v-if="loading" class="flex items-center gap-2 p-3 text-sm text-base-content/60"><span class="loading loading-spinner loading-xs"></span>加载会话中…</p>
        <p v-else-if="!store.groups.length" class="p-3 text-sm text-base-content/60">创建群聊，再从好友页面邀请 AI 角色。</p>
        <RouterLink v-for="group in store.groups" :key="group.id" :to="{ name: 'group-index', params: { group_id: group.id } }"
          class="mb-1 flex items-center gap-3 rounded-2xl p-3 transition-colors hover:bg-base-200" :class="{ 'bg-base-300/60': activeId === group.id }" :aria-current="activeId === group.id ? 'page' : undefined">
          <div class="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-base-300">
            <div v-if="group.characters.length" class="grid size-full gap-0.5 p-0.5" :class="group.characters.length > 1 ? 'grid-cols-2' : 'grid-cols-1'">
              <img v-for="character in group.characters.slice(0, 4)" :key="character.id" :src="character.photo" :alt="character.name" class="size-full min-h-0 object-cover" />
            </div>
            <GroupIcon v-else />
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <span class="truncate font-semibold">{{ group.name }}</span>
              <span class="shrink-0 text-xs text-base-content/50">{{ group.characters.length + 1 }} 人</span>
            </div>
            <p class="mt-1 truncate text-xs text-base-content/60">
              {{ group.latest_message ? `${group.latest_message.sender_name}：${group.latest_message.content || statusLabel[group.latest_message.status] || '暂无内容'}` : '暂无消息' }}
            </p>
          </div>
        </RouterLink>
      </div>
    </aside>

    <main class="flex min-h-0 min-w-0 flex-1 flex-col">
      <p v-if="pageError" class="bg-error/10 px-4 py-2 text-sm text-error" role="alert">{{ pageError }}</p>
      <template v-if="activeGroup && state">
        <header class="flex flex-wrap items-center justify-between gap-3 border-b border-base-200 p-4">
          <div class="min-w-0 flex-1">
            <h2 class="truncate text-lg font-bold">{{ activeGroup.name }} <span class="text-sm font-normal text-base-content/50">({{ activeGroup.characters.length + 1 }} 人)</span></h2>
            <p class="mt-1 flex items-center gap-1.5 text-xs text-base-content/60" role="status">
              <span class="size-1.5 rounded-full" :class="state.connected ? 'bg-success' : 'bg-warning'"></span>
              {{ state.connected ? '消息已同步' : '正在连接 / 恢复消息…' }}
            </p>
          </div>
          <div class="flex shrink-0 gap-1">
            <button class="btn btn-ghost btn-sm rounded-full" @click="openMembers">群成员</button>
            <RouterLink class="btn btn-sm rounded-full" :to="{ name: 'friend-index', query: { group_id: activeId } }">邀请好友</RouterLink>
          </div>
        </header>
        <div v-if="activeGroup.characters.length" class="flex shrink-0 items-center gap-2 overflow-x-auto border-b border-base-200 px-4 py-2">
          <span class="shrink-0 text-xs text-base-content/50">回复角色</span>
          <button class="btn btn-xs shrink-0 rounded-full" :class="state.target ? 'btn-ghost' : 'btn-success'" @click="state.target = ''">随机</button>
          <button v-for="character in activeGroup.characters" :key="character.id" class="btn btn-xs h-8 shrink-0 rounded-full" :class="Number(state.target) === character.id ? 'btn-success' : 'btn-ghost'"
            :aria-pressed="Number(state.target) === character.id" @click="state.target = Number(state.target) === character.id ? '' : String(character.id)">
            <img :src="character.photo" alt="" class="size-5 rounded-full object-cover" />{{ character.name }}
          </button>
        </div>
        <p v-if="state.error" class="bg-warning/10 px-4 py-2 text-sm text-warning" role="alert">{{ state.error }}</p>
        <div ref="scroll" class="min-h-0 flex-1 overflow-y-auto bg-base-200/20 p-4 md:p-6" @scroll="rememberScroll">
          <div v-if="!state.messages.length" class="flex h-full flex-col items-center justify-center gap-3 text-center text-base-content/60">
            <span class="flex size-16 items-center justify-center rounded-2xl bg-base-200"><GroupIcon /></span>
            <p>{{ activeGroup.characters.length ? '发一条消息，开始和 AI 角色交流' : '群聊已创建，先邀请 AI 角色加入' }}</p>
            <RouterLink v-if="!activeGroup.characters.length" class="btn btn-sm rounded-full" :to="{ name: 'friend-index', query: { group_id: activeId } }">去好友页选择角色</RouterLink>
          </div>
          <div v-for="message in bubbles" :key="message.bubbleKey" class="chat" :class="message.role === 'user' ? 'chat-end' : 'chat-start'">
            <div class="chat-image avatar" :class="{ 'avatar-placeholder': !messagePhoto(message) }">
              <div class="w-10 rounded-full bg-base-300">
                <img v-if="messagePhoto(message)" :src="messagePhoto(message)" :alt="`${message.sender_name}的头像`" />
                <span v-else class="text-sm">{{ message.sender_name?.slice(0, 1) || '?' }}</span>
              </div>
            </div>
            <div class="chat-header mb-1 text-xs text-base-content/60">{{ message.sender_name }}</div>
            <div class="chat-bubble max-w-[85%] whitespace-pre-wrap break-words md:max-w-[75%]" :class="{ 'chat-bubble-success': message.role === 'user' }">
              <span v-if="!message.content && ['pending', 'generating'].includes(message.status)" class="loading loading-dots loading-xs mr-1" aria-hidden="true"></span>
              {{ message.content || statusLabel[message.status] || '…' }}
            </div>
            <div class="chat-footer mt-1 flex items-center gap-2 text-xs">
              <span v-if="message.status !== 'completed'" :class="{ 'text-error': message.status === 'failed' }">{{ message.error || statusLabel[message.status] }}</span>
              <span v-else>{{ message.role === 'user' ? '已发送' : '回复完成' }}</span>
              <button v-if="message.status === 'failed' && canRetry(message)" class="link text-error" :disabled="retrying !== null || state.sending" @click="retry(message)">{{ retrying === message.id ? '重试中…' : '重试' }}</button>
            </div>
          </div>
        </div>
        <form class="shrink-0 border-t border-base-200 p-4" @submit.prevent="send">
          <div class="flex items-end gap-2">
            <textarea v-model="state.draft" class="textarea min-w-0 flex-1 resize-none rounded-2xl bg-base-200/50" rows="2" maxlength="2000" placeholder="输入消息，Enter 发送，Shift+Enter 换行" aria-label="群聊消息"
              :disabled="!activeGroup.characters.length" @keydown.enter="event => { if (!event.shiftKey && !event.isComposing) { event.preventDefault(); send() } }"></textarea>
            <button class="btn btn-success h-12 rounded-2xl" :disabled="state.sending || !state.draft.trim() || !activeGroup.characters.length">
              <span v-if="state.sending" class="loading loading-spinner loading-xs"></span><SendIcon v-else />发送
            </button>
          </div>
          <p class="mt-2 text-xs text-base-content/50">{{ state.target ? `由 ${activeGroup.characters.find(character => character.id === Number(state.target))?.name || '选中角色'} 回复` : '未指定角色时，随机一位群成员回复' }}</p>
        </form>
      </template>
      <div v-else class="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-base-content/60">
        <GroupIcon />{{ activeId && !loading ? '群聊不存在或无权访问' : '选择一个会话，或新建 AI 群聊' }}
      </div>
    </main>

    <dialog ref="create-dialog" class="modal">
      <form class="modal-box max-w-md rounded-2xl" @submit.prevent="createGroup">
        <h2 class="text-xl font-bold">新建 AI 群聊</h2>
        <label class="mt-4 block" for="group-name">群聊名称</label>
        <input id="group-name" v-model="name" class="input mt-2 w-full rounded-2xl" maxlength="50" required :disabled="creating" placeholder="例如：我的 AI 讨论室" />
        <p v-if="createError" class="mt-3 text-error" role="alert">{{ createError }}</p>
        <div class="modal-action">
          <button type="button" class="btn btn-ghost rounded-full" :disabled="creating" @click="createDialog.close()">取消</button>
          <button class="btn btn-success rounded-full" :disabled="creating || !name.trim()">{{ creating ? '创建中…' : '创建' }}</button>
        </div>
      </form>
    </dialog>

    <dialog ref="members-dialog" class="modal" @cancel="event => { if (removing) event.preventDefault() }">
      <div class="modal-box max-w-md rounded-2xl">
        <h2 class="text-xl font-bold">群成员</h2>
        <p class="mt-2 text-sm text-base-content/60">移出群聊后，该角色仍会保留在你的好友列表。</p>
        <div class="mt-4 max-h-72 overflow-y-auto">
          <div class="flex items-center gap-3 rounded-xl p-2">
            <div class="avatar"><div class="w-10 rounded-full"><img :src="user.photo" :alt="user.username" /></div></div>
            <span class="min-w-0 flex-1 truncate">{{ user.username }}</span><span class="badge badge-ghost badge-sm">群主</span>
          </div>
          <div v-for="character in activeGroup?.characters || []" :key="character.id" class="flex items-center gap-3 rounded-xl p-2 hover:bg-base-200">
            <div class="avatar"><div class="w-10 rounded-full"><img :src="character.photo" :alt="character.name" /></div></div>
            <span class="min-w-0 flex-1 truncate">{{ character.name }}</span>
            <button class="btn btn-ghost btn-sm text-error" :disabled="removing" :aria-label="`将${character.name}移出群聊`" @click="removeCandidate = character; memberError = ''">移出群聊</button>
          </div>
        </div>
        <div v-if="removeCandidate" class="mt-4 rounded-xl bg-warning/10 p-3 text-sm" role="status">
          确认将 <strong>{{ removeCandidate.name }}</strong> 移出本群？聊天记录会保留，尚未完成的回复会停止。
        </div>
        <p v-if="memberError" class="mt-3 text-sm text-error" role="alert">{{ memberError }}</p>
        <div class="modal-action">
          <template v-if="removeCandidate">
            <button class="btn btn-ghost rounded-full" :disabled="removing" @click="removeCandidate = null; memberError = ''">取消</button>
            <button class="btn btn-error rounded-full" :disabled="removing" @click="removeMember">{{ removing ? '移出中…' : '确认移出' }}</button>
          </template>
          <button v-else class="btn rounded-full" :disabled="removing" @click="membersDialog.close()">完成</button>
        </div>
      </div>
    </dialog>
  </div>
</template>
