<script setup lang="ts">
import { computed } from 'vue'

import type { FieldDefOut } from '@/api/types'
import FieldInput from '@/components/FieldInput.vue'

const props = defineProps<{ specs: FieldDefOut[]; modelValue: Record<string, unknown>; errors?: Record<string, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()

const groups = computed(() => {
  const inherited = props.specs.filter((s) => s.inherited_from)
  const own = props.specs.filter((s) => !s.inherited_from)
  return [
    { title: 'Shared fields', specs: inherited },
    { title: inherited.length ? 'This category' : '', specs: own },
  ].filter((g) => g.specs.length)
})

function update(key: string, value: unknown) {
  const next = { ...props.modelValue }
  if (value === null || value === undefined) delete next[key]
  else next[key] = value
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="stack">
    <div v-for="g in groups" :key="g.title" class="stack">
      <h3 v-if="g.title" class="muted group">{{ g.title }}</h3>
      <div class="grid-2">
        <div v-for="s in g.specs" :key="s.key" class="field" :data-test="`field-${s.key}`">
          <label :for="`f-${s.key}`">{{ s.label }}<span v-if="s.required"> *</span></label>
          <FieldInput :spec="s" :model-value="modelValue[s.key]" @update:model-value="(v) => update(s.key, v)" />
          <span v-if="s.help_text" class="muted">{{ s.help_text }}</span>
          <span v-if="errors?.[s.key]" class="error">{{ errors[s.key] }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group { font-size: .85rem; margin: 0; }
</style>
