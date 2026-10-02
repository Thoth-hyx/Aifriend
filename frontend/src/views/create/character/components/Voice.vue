<script setup>
import {onBeforeUnmount, ref, watch} from "vue";
import api from '@/js/http/api.js'
import { voiceUploadError } from '@/js/voiceUpload.js'
import { useUserStore } from '@/stores/user.js'

const props = defineProps(['voices', 'curVoiceId'])
const emit = defineEmits(['voiceCreated'])
const user = useUserStore()
const myVoice = ref(props.curVoiceId)
const audioFile = ref(null)
const preview = ref('')
const duration = ref(null)
const voiceName = ref('')
const cloning = ref(false)
const uploadProgress = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
let disposed = false

watch(()=>props.curVoiceId,newVal =>{
  myVoice.value = newVal
})

function chooseAudio(event) {
  const file = event.target.files?.[0] ?? null
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
  duration.value = null
  audioFile.value = file
  errorMessage.value = voiceUploadError(file)
  successMessage.value = ''
  if (file && !errorMessage.value) {
    preview.value = URL.createObjectURL(file)
    if (!voiceName.value.trim()) voiceName.value = file.name.replace(/\.[^.]+$/, '').slice(0, 100)
  }
}

function inspectDuration(event) {
  duration.value = event.target.duration
  errorMessage.value = voiceUploadError(audioFile.value, duration.value)
}

async function cloneVoice() {
  if (!user.canCloneVoice || cloning.value) return
  errorMessage.value = voiceUploadError(audioFile.value, duration.value)
  if (!errorMessage.value && !voiceName.value.trim()) errorMessage.value = '请输入音色名称'
  if (errorMessage.value) return
  const form = new FormData()
  form.append('name', voiceName.value.trim())
  form.append('audio', audioFile.value)
  cloning.value = true
  uploadProgress.value = 0
  successMessage.value = ''
  try {
    const { data } = await api.post('/api/create/character/voice/clone/', form, {
      timeout: 120000,
      onUploadProgress: event => {
        uploadProgress.value = Math.min(100, Math.round(event.loaded / (event.total || event.loaded) * 100))
      },
    })
    if (disposed) return
    if (data.result !== 'success') {
      errorMessage.value = data.result || '音色复刻失败'
      return
    }
    myVoice.value = data.voice.id
    emit('voiceCreated', data.voice)
    successMessage.value = `音色“${data.voice.name}”已加入音色库并选中`
  } catch (error) {
    if (disposed) return
    const data = error.response?.data
    errorMessage.value = error.response?.status === 403 ? '仅管理员可以复刻音色' :
        data?.result || '请求结果未确认，请检查音色库后再决定是否重新提交'
    if (data?.provider_code) errorMessage.value += `（${data.provider_code}）`
    if (data?.request_id) errorMessage.value += `，请求 ID：${data.request_id}`
  } finally {
    cloning.value = false
  }
}

onBeforeUnmount(() => {
  disposed = true
  if (preview.value) URL.revokeObjectURL(preview.value)
})

defineExpose({
  myVoice,
  cloning,
})

</script>

<template>
  <fieldset class="fieldset">
    <label class="label text-base">音色</label>
    <select v-model="myVoice" class="select w-full" :disabled="cloning" aria-label="角色音色">
      <option v-if="!voices.length" :value="null" disabled>{{ user.canCloneVoice ? '暂无音色，可上传录音复刻' : '暂无可用音色' }}</option>
      <option
          v-for="voice in voices"
          :key="voice.id"
          :id = "voice.id"
          :value = "voice.id"
      >{{ voice.name }}{{ voice.is_custom ? '（我的复刻音色）' : '' }}</option>
    </select>
    <details v-if="user.canCloneVoice" class="mt-2 rounded-xl border border-base-300 bg-base-100 p-3">
      <summary class="cursor-pointer text-sm font-medium">上传音频复刻音色</summary>
      <div class="mt-3 flex flex-col gap-3">
        <p class="text-xs text-base-content/60">支持 WAV（16bit）、MP3、M4A，文件不超过 10 MB。建议 10～20 秒清晰朗读，至少 5 秒、最长 60 秒；采样率至少 16 kHz。</p>
        <label class="fieldset-label">音色名称
          <input v-model="voiceName" class="input w-full" maxlength="100" :disabled="cloning" placeholder="例如：我的声音" />
        </label>
        <label class="fieldset-label">朗读录音
          <input type="file" class="file-input w-full" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4,audio/x-m4a" :disabled="cloning" @change="chooseAudio" />
        </label>
        <audio v-if="preview" :src="preview" controls class="w-full" aria-label="试听上传的录音" @loadedmetadata="inspectDuration"></audio>
        <p class="text-xs text-base-content/60">请使用本人或已获授权的声音，避免背景音乐、噪音和多人讲话。</p>
        <p v-if="errorMessage" class="break-words text-sm text-error" role="alert">{{ errorMessage }}</p>
        <p v-if="successMessage" class="text-sm text-success" role="status">{{ successMessage }}</p>
        <button type="button" class="btn btn-neutral" :disabled="cloning || !audioFile || !voiceName.trim()" @click="cloneVoice">
          <span v-if="cloning" class="loading loading-spinner loading-xs" aria-hidden="true"></span>
          {{ cloning ? (uploadProgress < 100 ? `上传中 ${uploadProgress}%` : '音色复刻中…') : '复刻并加入音色库' }}
        </button>
      </div>
    </details>
  </fieldset>
</template>

<style scoped>

</style>
