<script setup>
import {ref, watch} from "vue";

const props = defineProps(['profile'])
const myProfile = ref(props.profile)

watch(()=>props.profile,newVal =>{
  myProfile.value = newVal
})

defineExpose({
  myProfile,
})

</script>

<template>
  <fieldser class="fieldset">
    <label class="label text-base">角色介绍</label>
    <textarea v-model="myProfile" rows="6" class="textarea w-108"></textarea>
  </fieldser>
</template>

<style scoped>

</style>