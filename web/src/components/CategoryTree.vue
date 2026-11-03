<script setup lang="ts">
import { computed } from 'vue'

import type { CategoryOut } from '@/api/types'

const props = defineProps<{ categories: CategoryOut[]; selectedId?: number | null }>()
const emit = defineEmits<{ select: [id: number] }>()

interface Row {
  cat: CategoryOut
  depth: number
}

const rows = computed<Row[]>(() => {
  const children = new Map<number | null, CategoryOut[]>()
  for (const c of props.categories) {
    const list = children.get(c.parent_id ?? null) ?? []
    list.push(c)
    children.set(c.parent_id ?? null, list)
  }
  const out: Row[] = []
  const walk = (parent: number | null, depth: number) => {
    for (const c of (children.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name))) {
      out.push({ cat: c, depth })
      walk(c.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})
</script>

<template>
  <ul class="tree" role="tree">
    <li
      v-for="r in rows"
      :key="r.cat.id"
      role="treeitem"
      :aria-selected="r.cat.id === selectedId"
      :class="{ selected: r.cat.id === selectedId }"
      :style="{ paddingLeft: `${r.depth * 1.1 + 0.4}rem` }"
      :data-test="`category-${r.cat.id}`"
      @click="emit('select', r.cat.id)"
    >
      <i :class="['pi', r.cat.effective_tracking_mode === 'unit' ? 'pi-th-large' : 'pi-folder']" />
      {{ r.cat.name }}
      <span v-if="r.cat.effective_tracking_mode === 'unit'" class="badge">per unit</span>
    </li>
  </ul>
</template>

<style scoped>
.tree { list-style: none; margin: 0; padding: 0; }
.tree li { padding: .35rem .4rem; border-radius: 6px; cursor: pointer; display: flex; gap: .4rem; align-items: center; }
.tree li:hover { background: var(--p2l-bg); }
.tree li.selected { background: var(--p2l-bg); color: var(--p2l-accent); font-weight: 600; }
</style>
