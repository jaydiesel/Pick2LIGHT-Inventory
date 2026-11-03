<script setup lang="ts">
import type { LatestOut, LogEntryTypeOut } from '@/api/types'

defineProps<{ latest: Record<string, LatestOut>; logTypes: LogEntryTypeOut[] }>()

function name(types: LogEntryTypeOut[], key: string) {
  return types.find((t) => t.key === key)?.name ?? key
}
function label(types: LogEntryTypeOut[], typeKey: string, field: string) {
  const t = types.find((x) => x.key === typeKey)
  return ((t?.fields ?? []).find((f) => f.key === field)?.label as string | undefined) ?? field
}
</script>

<template>
  <div class="latest">
    <div v-for="(l, key) in latest" :key="key" class="card tile" :data-test="`latest-${key}`">
      <div class="muted">{{ name(logTypes, String(key)) }} · {{ new Date(l.performed_at).toLocaleDateString() }}</div>
      <div v-for="(v, f) in l.values_display" :key="f" class="value">
        <span class="muted">{{ label(logTypes, String(key), String(f)) }}</span> <b>{{ v }}</b>
      </div>
    </div>
  </div>
</template>

<style scoped>
.latest { display: flex; gap: var(--p2l-gap); flex-wrap: wrap; }
.tile { margin: 0; min-width: 200px; }
.value { font-size: 1.1rem; }
</style>
