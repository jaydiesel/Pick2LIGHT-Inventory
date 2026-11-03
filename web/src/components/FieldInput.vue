<script setup lang="ts">
import { computed } from 'vue'

import type { FieldDefOut } from '@/api/types'
import SiNumberInput from '@/components/SiNumberInput.vue'

const props = defineProps<{ spec: FieldDefOut; modelValue: unknown }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
const id = computed(() => `f-${props.spec.key}`)
const options = computed(() => (props.spec.options ?? []) as { value: string; label?: string | null }[])
const selected = computed(() => (Array.isArray(props.modelValue) ? (props.modelValue as string[]) : []))

function toggle(value: string, on: boolean) {
  const next = selected.value.filter((v) => v !== value)
  if (on) next.push(value)
  emit('update:modelValue', next.length ? next : null)
}

function set(value: unknown) {
  emit('update:modelValue', value === '' ? null : value)
}
</script>

<template>
  <textarea
    v-if="spec.type === 'long_text'"
    :id="id"
    class="p2l-input"
    rows="3"
    :value="(modelValue as string) ?? ''"
    @input="set(($event.target as HTMLTextAreaElement).value)"
  />
  <SiNumberInput
    v-else-if="spec.type === 'number'"
    :id="id"
    :model-value="typeof modelValue === 'number' ? modelValue : null"
    :unit="spec.number_unit"
    :allow-prefixes="spec.number_si_prefixes"
    :decimals="spec.decimals"
    @update:model-value="set"
  />
  <select v-else-if="spec.type === 'select'" :id="id" class="p2l-input" :value="(modelValue as string) ?? ''" @change="set(($event.target as HTMLSelectElement).value)">
    <option value="">—</option>
    <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label || o.value }}</option>
  </select>
  <span v-else-if="spec.type === 'multi_select'" class="row">
    <label v-for="o in options" :key="o.value" class="row">
      <input type="checkbox" :checked="selected.includes(o.value)" @change="toggle(o.value, ($event.target as HTMLInputElement).checked)" />
      {{ o.label || o.value }}
    </label>
  </span>
  <input
    v-else-if="spec.type === 'boolean'"
    :id="id"
    type="checkbox"
    :checked="modelValue === true"
    @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
  />
  <input v-else-if="spec.type === 'date'" :id="id" class="p2l-input" type="date" :value="(modelValue as string) ?? ''" @change="set(($event.target as HTMLInputElement).value)" />
  <input v-else-if="spec.type === 'url'" :id="id" class="p2l-input" type="url" placeholder="https://" :value="(modelValue as string) ?? ''" @change="set(($event.target as HTMLInputElement).value)" />
  <input
    v-else-if="spec.type === 'file'"
    :id="id"
    class="p2l-input"
    type="number"
    min="1"
    placeholder="Attachment id"
    :value="(modelValue as number) ?? ''"
    @change="set(Number(($event.target as HTMLInputElement).value) || null)"
  />
  <input v-else :id="id" class="p2l-input" type="text" :value="(modelValue as string) ?? ''" @change="set(($event.target as HTMLInputElement).value)" />
</template>
