<script setup>
import {ref, watch} from "vue";

const props = defineProps(['name'])
const myName = ref(props.name)

watch(()=>props.name,newVal =>{
  myName.value = newVal
})

defineExpose({
  myName,
})

</script>

<template>
  <fieldser class="fieldset">
    <label class="label text-base">名字</label>
    <input v-model="myName" type="text" class="input w-108">
  </fieldser>
</template>

<style scoped>

</style>