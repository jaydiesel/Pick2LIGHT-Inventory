<script setup lang="ts">
import { ref, watch } from 'vue'

import { formatQuantity, parseQuantity } from '@/lib/si'

const props = withDefaults(
  defineProps<{ modelValue: number | null | undefined; unit?: string | null; allowPrefixes?: boolean; decimals?: number | null; id?: string }>(),
  { unit: null, allowPrefixes: false, decimals: null, id: undefined },
)
const emit = defineEmits<{ 'update:modelValue': [value: number | null] }>()

const text = ref('')
const error = ref('')
const focused = ref(false)

function display(v: number | null | undefined): string {
  if (v === null || v === undefined || typeof v !== 'number') return v == null ? '' : String(v)
  return formatQuantity(v, props.unit, props.decimals ?? undefined, props.allowPrefixes)
}

watch(
  () => props.modelValue,
  (v) => {
    if (!focused.value) text.value = display(v)
  },
  { immediate: true },
)

function commit() {
  focused.value = false
  const raw = text.value.trim()
  if (!raw) {
    error.value = ''
    emit('update:modelValue', null)
    return
  }
  try {
    const value = parseQuantity(raw, props.unit, props.allowPrefixes)
    error.value = ''
    emit('update:modelValue', value)
    text.value = display(value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}
</script>

<template>
  <span class="si">
    <input
      :id="id"
      v-model="text"
      class="p2l-input"
      inputmode="decimal"
      :placeholder="allowPrefixes ? `e.g. 4.7k${unit ?? ''}` : unit ?? ''"
      :aria-invalid="!!error"
      @focus="focused = true"
      @blur="commit"
      @keydown.enter.prevent="commit"
    />
    <span v-if="error" class="error">{{ error }}</span>
  </span>
</template>

<style scoped>
.si { display: flex; flex-direction: column; gap: .2rem; }
</style>
