<script setup>
import {ref, watch} from "vue";

const props = defineProps(['voices', 'curVoiceId'])
const myVoice = ref(props.curVoiceId)

watch(()=>props.curVoiceId,newVal =>{
  myVoice.value = newVal
})

defineExpose({
  myVoice,
})

</script>

<template>
  <fieldser class="fieldset">
    <label class="label text-base">音色</label>
    <select v-model="myVoice" class="select">
      <option
          v-for="voice in voices"
          :id = "voice.id"
          :value = "voice.id"
      >{{ voice.name }}</option>
    </select>
  </fieldser>
</template>

<style scoped>

</style>