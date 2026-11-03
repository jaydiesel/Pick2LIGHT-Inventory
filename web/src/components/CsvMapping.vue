<script setup lang="ts">
import { onMounted, watch } from 'vue'

import type { FieldDefOut } from '@/api/types'
import { autoMap, BASE_TARGETS } from '@/lib/csvMapping'

const props = defineProps<{ headers: string[]; specs: FieldDefOut[]; modelValue: Record<string, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, string>] }>()

function init() {
  const auto = autoMap(props.headers, props.specs)
  const merged: Record<string, string> = {}
  for (const h of props.headers) merged[h] = props.modelValue[h] ?? auto[h]
  emit('update:modelValue', merged)
}

function set(header: string, target: string) {
  emit('update:modelValue', { ...props.modelValue, [header]: target })
}

watch(() => [props.headers, props.specs], init)
onMounted(init)
</script>

<template>
  <table class="plain">
    <thead><tr><th>Column in your file</th><th>Goes to</th></tr></thead>
    <tbody>
      <tr v-for="h in headers" :key="h">
        <td>{{ h }}</td>
        <td>
          <select class="p2l-input" :value="modelValue[h] ?? 'ignore'" :data-test="`map-${h}`" @change="set(h, ($event.target as HTMLSelectElement).value)">
            <option value="ignore">— ignore —</option>
            <optgroup label="Item">
              <option v-for="t in BASE_TARGETS" :key="t.value" :value="t.value">{{ t.label }}</option>
            </optgroup>
            <optgroup v-if="specs.length" label="Fields">
              <option v-for="s in specs" :key="s.key" :value="`attr.${s.key}`">{{ s.label }}</option>
            </optgroup>
          </select>
        </td>
      </tr>
    </tbody>
  </table>
</template>
