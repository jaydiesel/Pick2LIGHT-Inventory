<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

import { ApiError, apiFetch } from '@/api/client'
import type { AttachmentOut } from '@/api/types'

const props = defineProps<{ ownerType: string; ownerId: number }>()
const items = ref<AttachmentOut[]>([])
const kind = ref('datasheet')
const url = ref('')
const error = ref('')

async function load() {
  items.value = await apiFetch<AttachmentOut[]>(`/attachments?owner_type=${props.ownerType}&owner_id=${props.ownerId}`)
}

function fail(e: unknown) {
  error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
}

async function upload(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const body = new FormData()
  body.append('file', file)
  body.append('owner_type', props.ownerType)
  body.append('owner_id', String(props.ownerId))
  body.append('kind', kind.value)
  error.value = ''
  try {
    await apiFetch('/attachments', { method: 'POST', body })
    input.value = ''
    await load()
  } catch (e) {
    fail(e)
  }
}

async function addLink() {
  error.value = ''
  try {
    await apiFetch('/attachments/link', {
      method: 'POST',
      json: { owner_type: props.ownerType, owner_id: props.ownerId, kind: kind.value, url: url.value.trim() },
    })
    url.value = ''
    await load()
  } catch (e) {
    fail(e)
  }
}

async function remove(a: AttachmentOut) {
  if (!window.confirm(`Remove ${a.filename}?`)) return
  await apiFetch(`/attachments/${a.id}`, { method: 'DELETE' }).catch(fail)
  await load()
}

watch(() => props.ownerId, load)
onMounted(load)
</script>

<template>
  <div class="stack">
    <ul v-if="items.length" class="files">
      <li v-for="a in items" :key="a.id" class="row">
        <i :class="['pi', a.kind === 'photo' ? 'pi-image' : a.kind === 'datasheet' ? 'pi-file-pdf' : 'pi-file']" />
        <a :href="`/api/v1/attachments/${a.id}/file`" target="_blank" rel="noopener">{{ a.filename }}</a>
        <span class="badge">{{ a.kind }}</span>
        <span class="spacer" />
        <button class="p2l-btn" aria-label="Remove" @click="remove(a)"><i class="pi pi-trash" /></button>
      </li>
    </ul>
    <p v-else class="muted">No files yet.</p>
    <div class="row">
      <select v-model="kind" class="p2l-input">
        <option value="datasheet">Datasheet</option>
        <option value="photo">Photo</option>
        <option value="document">Document</option>
        <option value="other">Other</option>
      </select>
      <input type="file" @change="upload" />
    </div>
    <form class="row" @submit.prevent="addLink">
      <input v-model="url" class="p2l-input spacer" type="url" placeholder="…or paste a link to a datasheet" />
      <button class="p2l-btn" :disabled="!url.trim()">Add link</button>
    </form>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.files { list-style: none; margin: 0; padding: 0; }
.files li { padding: .3rem 0; border-bottom: 1px solid var(--p2l-border); }
</style>
