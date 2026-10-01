import { defineStore } from 'pinia'
import { reactive, ref, watch } from 'vue'
import api from '@/js/http/api.js'
import { useUserStore } from '@/stores/user.js'
import { mergeMessages } from '@/js/groupMessages.js'

export const useGroupStore = defineStore('group', () => {
  const user = useUserStore()
  const groups = ref([])
  const sessions = reactive({})
  let epoch = 0
  let listRequest = 0
  watch(() => user.id, () => {
    epoch++
    groups.value = []
    for (const id of Object.keys(sessions)) delete sessions[id]
  }, { flush: 'sync' })

  function session(id) {
    return sessions[id] ??= {
      messages: [], cursor: 0, syncing: false, connected: false,
      sending: false, error: '', draft: '', target: '', scrollTop: null,
    }
  }

  function errorText(error) {
    return error.response?.data?.result || error.response?.data?.detail || '连接暂时中断，正在重试'
  }

  async function loadGroups() {
    const currentEpoch = epoch
    const requestId = ++listRequest
    const { data } = await api.get('/api/groups/', { timeout: 8000 })
    if (currentEpoch !== epoch || requestId !== listRequest) return false
    groups.value = data.groups
    return true
  }

  async function sync(id) {
    const state = session(id)
    if (state.syncing) return
    state.syncing = true
    const currentEpoch = epoch
    try {
      let more = true
      while (more && currentEpoch === epoch) {
        const { data } = await api.get(`/api/groups/${id}/messages/`, {
          params: { after_revision: state.cursor }, timeout: 8000,
        })
        if (currentEpoch !== epoch) return
        state.messages = mergeMessages(state.messages, data.messages)
        state.cursor = data.cursor
        more = data.has_more
      }
      state.connected = true
      state.error = ''
    } catch (error) {
      state.connected = false
      state.error = errorText(error)
    } finally {
      state.syncing = false
    }
  }

  async function send(id, content, target = null, clientId = crypto.randomUUID()) {
    const state = session(id)
    const currentEpoch = epoch
    const localId = `local:${clientId}`
    const optimistic = {
      id: localId, group_id: id, role: 'user', sender_name: user.username,
      content, status: 'sending', client_message_id: clientId,
      requested_character_id: target, revision: 0, create_time: new Date().toISOString(),
    }
    state.messages = mergeMessages(state.messages, [optimistic])
    state.sending = true
    try {
      const { data } = await api.post(`/api/groups/${id}/messages/`, {
        content, character_id: target, client_message_id: clientId,
      }, { timeout: 10000 })
      if (currentEpoch !== epoch) return
      state.messages = mergeMessages(state.messages, data.messages)
    } catch (error) {
      if (currentEpoch !== epoch) return
      const local = state.messages.find(message => message.id === localId)
      if (local) {
        local.status = 'failed'
        local.error = error.response ? errorText(error) : '发送结果未确认，重试不会重复发送'
      }
    } finally {
      state.sending = false
    }
  }

  async function retry(id, message) {
    if (message.role === 'user') {
      return send(id, message.content, message.requested_character_id, message.client_message_id)
    }
    const currentEpoch = epoch
    const { data } = await api.post(`/api/groups/${id}/messages/${message.id}/retry/`)
    if (currentEpoch === epoch) {
      const state = session(id)
      state.messages = mergeMessages(state.messages, [data.message])
    }
  }

  async function removeCharacter(id, characterId) {
    const currentEpoch = epoch
    const { data } = await api.delete(`/api/groups/${id}/characters/`, {
      data: { character_id: characterId }, timeout: 10000,
    })
    if (currentEpoch !== epoch) return
    listRequest++ // Ignore list snapshots requested before the removal completed.
    groups.value = groups.value.map(group => group.id === id ? data.group : group)
    const state = session(id)
    if (Number(state.target) === characterId) state.target = ''
    await sync(id)
  }

  return { groups, session, loadGroups, sync, send, retry, removeCharacter, errorText }
})
