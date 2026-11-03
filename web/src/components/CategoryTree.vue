<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../api/schema'

type CategoryOut = components['schemas']['CategoryOut']

const props = defineProps<{
  categories: CategoryOut[]
  selectedId?: number | null
  /** Categories shown but not selectable (e.g. the category being moved). */
  disabledIds?: number[]
}>()
const emit = defineEmits<{ select: [id: number] }>()

interface Row {
  category: CategoryOut
  depth: number
}

/** Depth-first flattening of the parent_id tree; orphans (unknown parent) are shown at the top. */
const rows = computed<Row[]>(() => {
  const ids = new Set(props.categories.map((c) => c.id))
  const children = new Map<number | null, CategoryOut[]>()
  for (const c of props.categories) {
    const key = c.parent_id != null && ids.has(c.parent_id) ? c.parent_id : null
    children.set(key, [...(children.get(key) ?? []), c])
  }
  const out: Row[] = []
  const walk = (parent: number | null, depth: number) => {
    for (const c of children.get(parent) ?? []) {
      out.push({ category: c, depth })
      walk(c.id, depth + 1)
    }
  }
  walk(null, 0)
  return out
})

function pick(id: number) {
  if (!props.disabledIds?.includes(id)) emit('select', id)
}
</script>

<template>
  <ul class="category-tree" role="tree">
    <li v-for="row in rows" :key="row.category.id" role="treeitem" :aria-selected="selectedId === row.category.id" :aria-level="row.depth + 1">
      <button
        type="button"
        class="node"
        :class="{ selected: selectedId === row.category.id }"
        :style="{ marginLeft: `${row.depth * 1.25}rem` }"
        :data-test="`cat-${row.category.id}`"
        :data-depth="row.depth"
        :disabled="disabledIds?.includes(row.category.id)"
        @click="pick(row.category.id)"
      >
        <i v-if="row.category.icon" class="pi" :class="row.category.icon" />
        <span>{{ row.category.name }}</span>
      </button>
    </li>
  </ul>
</template>

<style scoped>
.category-tree { list-style: none; margin: 0; padding: 0; }
.node { background: none; border: 0; color: inherit; font: inherit; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; display: inline-flex; gap: 0.4rem; align-items: center; }
.node:hover:not(:disabled) { background: var(--p-content-hover-background); }
.node.selected { background: var(--p-highlight-background); color: var(--p-highlight-color); font-weight: 600; }
.node:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
