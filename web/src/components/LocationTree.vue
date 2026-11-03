<script setup lang="ts">
import { computed, ref } from 'vue'

import type { LocationNode } from '@/api/types'
import { loadJson, saveJson } from '@/lib/storage'

const props = defineProps<{ nodes: LocationNode[]; selectedId?: number | null }>()
const emit = defineEmits<{ select: [id: number] }>()

const STORE_KEY = 'p2l.locationTree.collapsed'
const collapsed = ref<Set<number>>(new Set(loadJson<number[]>(STORE_KEY, [])))

interface Row {
  node: LocationNode
  depth: number
  hasChildren: boolean
}

const rows = computed<Row[]>(() => {
  const out: Row[] = []
  const walk = (nodes: LocationNode[], depth: number) => {
    for (const n of nodes) {
      const kids = n.children ?? []
      out.push({ node: n, depth, hasChildren: kids.length > 0 })
      if (!collapsed.value.has(n.id)) walk(kids, depth + 1)
    }
  }
  walk(props.nodes, 0)
  return out
})

function toggle(id: number) {
  const next = new Set(collapsed.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsed.value = next
  saveJson(STORE_KEY, [...next])
}
</script>

<template>
  <ul class="tree" role="tree">
    <li
      v-for="r in rows"
      :key="r.node.id"
      role="treeitem"
      :aria-selected="r.node.id === selectedId"
      :class="{ selected: r.node.id === selectedId }"
      :style="{ paddingLeft: `${r.depth * 1.1}rem` }"
      :data-test="`location-${r.node.id}`"
    >
      <button
        v-if="r.hasChildren"
        class="toggle"
        :aria-label="collapsed.has(r.node.id) ? 'Expand' : 'Collapse'"
        :data-test="`toggle-${r.node.id}`"
        @click="toggle(r.node.id)"
      >
        <i :class="['pi', collapsed.has(r.node.id) ? 'pi-chevron-right' : 'pi-chevron-down']" />
      </button>
      <span v-else class="toggle" />
      <span class="name" @click="emit('select', r.node.id)">
        {{ r.node.name }} <span class="muted">{{ r.node.code }}</span>
        <span v-if="r.node.type_name" class="badge">{{ r.node.type_name }}</span>
      </span>
      <slot name="actions" :node="r.node" />
    </li>
  </ul>
</template>

<style scoped>
.tree { list-style: none; margin: 0; padding: 0; }
.tree li { display: flex; gap: .35rem; align-items: center; padding: .25rem .3rem; border-radius: 6px; }
.tree li:hover { background: var(--p2l-bg); }
.tree li.selected { background: var(--p2l-bg); color: var(--p2l-accent); }
.toggle { width: 1.6rem; height: 1.6rem; border: 0; background: none; color: inherit; cursor: pointer; flex: none; }
.name { cursor: pointer; flex: 1; }
</style>
