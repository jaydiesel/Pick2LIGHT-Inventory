<script setup lang="ts">
import { computed, ref } from 'vue'
import type { components } from '../api/schema'

type LocationNode = components['schemas']['LocationNode']

const props = defineProps<{
  nodes: LocationNode[]
  selectable?: boolean
  selectedId?: number | null
}>()
const emit = defineEmits<{ select: [id: number] }>()

const STORAGE_KEY = 'p2l.locationTree.collapsed'

function loadCollapsed(): Set<number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(parsed) ? parsed.filter((v): v is number => typeof v === 'number') : [])
  } catch {
    return new Set()
  }
}

// Everything starts expanded; only collapsed ids are remembered.
const collapsed = ref(loadCollapsed())

function toggle(id: number) {
  const next = new Set(collapsed.value)
  if (!next.delete(id)) next.add(id)
  collapsed.value = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]))
  } catch {
    // storage unavailable; the in-memory state still works
  }
}

interface Row {
  node: LocationNode
  depth: number
}

const rows = computed<Row[]>(() => {
  const out: Row[] = []
  const walk = (nodes: LocationNode[], depth: number) => {
    for (const node of nodes) {
      out.push({ node, depth })
      if (!collapsed.value.has(node.id)) walk(node.children, depth + 1)
    }
  }
  walk(props.nodes, 0)
  return out
})
</script>

<template>
  <ul class="location-tree" role="tree">
    <li
      v-for="row in rows"
      :key="row.node.id"
      class="row"
      role="treeitem"
      :aria-level="row.depth + 1"
      :aria-expanded="row.node.children.length ? !collapsed.has(row.node.id) : undefined"
      :aria-selected="selectable ? selectedId === row.node.id : undefined"
      :style="{ paddingLeft: `${row.depth * 1.25}rem` }"
    >
      <button
        v-if="row.node.children.length"
        type="button"
        class="toggle"
        :data-test="`toggle-${row.node.id}`"
        :aria-label="collapsed.has(row.node.id) ? 'Expand' : 'Collapse'"
        @click="toggle(row.node.id)"
      >
        <i class="pi" :class="collapsed.has(row.node.id) ? 'pi-chevron-right' : 'pi-chevron-down'" />
      </button>
      <span v-else class="toggle spacer" />
      <component
        :is="selectable ? 'button' : 'span'"
        class="node"
        :class="{ selected: selectable && selectedId === row.node.id, selectable }"
        :type="selectable ? 'button' : undefined"
        :data-test="`loc-${row.node.id}`"
        :data-depth="row.depth"
        @click="selectable && emit('select', row.node.id)"
      >
        <span class="name">{{ row.node.name }}</span>
        <small class="muted">{{ row.node.code }}</small>
        <small v-if="row.node.type_name" class="muted">{{ row.node.type_name }}</small>
      </component>
      <span class="actions"><slot name="actions" :node="row.node" /></span>
    </li>
  </ul>
</template>

<style scoped>
.location-tree { list-style: none; margin: 0; padding: 0; }
.row { display: flex; align-items: center; gap: 0.25rem; }
.toggle { background: none; border: 0; color: inherit; width: 1.5rem; padding: 0.25rem 0; cursor: pointer; flex: none; }
.node { background: none; border: 0; color: inherit; font: inherit; padding: 0.25rem 0.5rem; border-radius: 4px; display: inline-flex; gap: 0.5rem; align-items: baseline; text-align: left; }
.node.selectable { cursor: pointer; }
.node.selectable:hover { background: var(--p-content-hover-background); }
.node.selected { background: var(--p-highlight-background); color: var(--p-highlight-color); font-weight: 600; }
.actions { margin-left: auto; display: inline-flex; gap: 0.25rem; }
</style>
