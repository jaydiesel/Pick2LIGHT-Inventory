<script setup lang="ts">
import Button from 'primevue/button'
import Select from 'primevue/select'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError, apiFetch, apiFetchBlob } from '../api/client'
import type { components } from '../api/schema'
import { useApiToast } from '../composables/useApiToast'

type LocationOut = components['schemas']['LocationOut']
type LocationNode = components['schemas']['LocationNode']
type SearchPage = components['schemas']['SearchPage']
type AttachmentOut = components['schemas']['AttachmentOut']
type TemplateOut = components['schemas']['TemplateOut']
type SheetSpec = components['schemas']['SheetSpec']

const route = useRoute()
const notify = useApiToast()

const id = computed(() => Number(route.params.id))
const location = ref<LocationOut | null>(null)
const children = ref<LocationNode[]>([])
const contents = ref<SearchPage>({ hits: [], total: 0 })
const photos = ref<AttachmentOut[]>([])
const templates = ref<TemplateOut[]>([])
const sheets = ref<SheetSpec[]>([])

const showChildPrint = ref(false)
const sheetId = ref<string | null>(null)
const startPosition = ref(0)

const locationTemplate = computed(() => templates.value.find((t) => t.target === 'location'))
const cells = computed(() => {
  const s = sheets.value.find((x) => x.id === sheetId.value)
  return s ? s.cols * s.rows : 1
})
const photoUrl = computed(() => {
  const photo = photos.value.find((p) => p.id === location.value?.photo_attachment_id) ?? photos.value[0]
  return photo ? `/api/v1/attachments/${photo.id}/file` : null
})

function findNode(nodes: LocationNode[], target: number): LocationNode | null {
  for (const n of nodes) {
    if (n.id === target) return n
    const hit = findNode(n.children, target)
    if (hit) return hit
  }
  return null
}

async function load() {
  location.value = null
  try {
    const [loc, tree, found, atts] = await Promise.all([
      apiFetch<LocationOut>(`/locations/${id.value}`),
      apiFetch<LocationNode[]>('/locations/tree'),
      apiFetch<SearchPage>('/search', { method: 'POST', json: { location_id: id.value, limit: 200 } }),
      apiFetch<AttachmentOut[]>(`/attachments?owner_type=location&owner_id=${id.value}`),
    ])
    location.value = loc
    children.value = findNode(tree, id.value)?.children ?? []
    contents.value = found
    photos.value = atts.filter((a) => a.kind === 'photo')
  } catch (e) {
    notify.error(e, 'Could not load location')
  }
}

onMounted(async () => {
  void load()
  try {
    ;[templates.value, sheets.value] = await Promise.all([
      apiFetch<TemplateOut[]>('/label-templates'),
      apiFetch<SheetSpec[]>('/label-sheets'),
    ])
    sheetId.value = sheets.value[0]?.id ?? null
  } catch (e) {
    notify.error(e, 'Could not load label settings')
  }
})
watch(id, load)

/**
 * Render a label PDF into a new tab. The tab must be opened synchronously inside the click
 * handler (before any await) or popup blockers refuse it.
 */
async function printLabels(ids: number[], sheet?: { sheet_id: string; start_position: number }) {
  const tab = window.open('', '_blank')
  try {
    const template = locationTemplate.value
    if (!template) throw new Error('No location label template is available')
    const blob = await apiFetchBlob('/labels/pdf', {
      method: 'POST',
      json: { template_id: template.id, target_type: 'location', ids, copies: 1, ...sheet },
    })
    const url = URL.createObjectURL(blob)
    if (tab) tab.location = url
    else notify.error(new Error('The browser blocked the label tab'))
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (e) {
    tab?.close()
    // An oversize label on a sheet is reported against the sheet selection; show that text.
    notify.error(e instanceof ApiError && e.fields.sheet_id ? new Error(e.fields.sheet_id) : e)
  }
}

const printOne = () => printLabels([id.value])
const printChildren = () =>
  printLabels(
    children.value.map((c) => c.id),
    { sheet_id: sheetId.value ?? '', start_position: Math.max(0, Math.min(startPosition.value || 0, cells.value - 1)) },
  )

async function uploadPhoto(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('owner_type', 'location')
  form.append('owner_id', String(id.value))
  form.append('kind', 'photo')
  try {
    await apiFetch('/attachments', { method: 'POST', body: form })
    await load()
  } catch (e) {
    notify.error(e)
  } finally {
    input.value = ''
  }
}
</script>

<template>
  <section v-if="location" class="location-detail">
    <nav class="breadcrumb" data-test="breadcrumb" aria-label="Location path">
      <RouterLink to="/locations">Locations</RouterLink>
      <template v-for="p in location.path" :key="p.id">
        <span class="sep">/</span>
        <RouterLink :to="`/locations/${p.id}`">{{ p.name }}</RouterLink>
      </template>
      <span class="sep">/</span>
      <strong>{{ location.name }}</strong>
    </nav>

    <h1>{{ location.name }}</h1>
    <dl class="facts">
      <dt>Code</dt><dd data-test="code">{{ location.code }}</dd>
      <dt>Type</dt><dd>{{ location.type_name ?? '—' }}</dd>
      <dt>Notes</dt><dd>{{ location.notes ?? '—' }}</dd>
    </dl>

    <div class="photo">
      <img v-if="photoUrl" :src="photoUrl" :alt="`Photo of ${location.name}`" />
      <label class="upload">
        <span class="muted">{{ photoUrl ? 'Add another photo' : 'Add a photo' }}</span>
        <input type="file" accept="image/*" data-test="photo-input" @change="uploadPhoto" />
      </label>
    </div>

    <div class="actions">
      <Button label="Print label" icon="pi pi-print" data-test="print-label" @click="printOne" />
      <Button
        label="Print labels for children"
        icon="pi pi-tags"
        severity="secondary"
        :disabled="!children.length"
        data-test="print-children"
        @click="showChildPrint = !showChildPrint"
      />
    </div>

    <div v-if="showChildPrint" class="child-print" data-test="child-print-panel">
      <label>Sheet
        <Select v-model="sheetId" :options="sheets" option-label="name" option-value="id" data-test="sheet-select" />
      </label>
      <label>Start position (0–{{ cells - 1 }})
        <input v-model.number="startPosition" type="number" min="0" :max="cells - 1" data-test="start-position" />
      </label>
      <Button :label="`Print ${children.length} labels`" :disabled="!sheetId" data-test="print-children-go" @click="printChildren" />
    </div>

    <h2>Sub-locations</h2>
    <ul v-if="children.length">
      <li v-for="c in children" :key="c.id"><RouterLink :to="`/locations/${c.id}`">{{ c.name }}</RouterLink> <small class="muted">{{ c.code }}</small></li>
    </ul>
    <p v-else class="muted">None.</p>

    <h2>Contents ({{ contents.total }})</h2>
    <ul v-if="contents.hits.length" data-test="contents">
      <li v-for="h in contents.hits" :key="h.id">
        <RouterLink :to="`/items/${h.id}`">{{ h.name }}</RouterLink>
        <small class="muted"> {{ h.sku }} · {{ h.category_name }} · on hand {{ h.on_hand }}</small>
      </li>
    </ul>
    <p v-else class="muted">Nothing stored here.</p>
  </section>
  <p v-else class="muted">Loading…</p>
</template>

<style scoped>
.breadcrumb { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: baseline; }
.sep { color: var(--p-text-muted-color); }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; }
.facts dt { color: var(--p-text-muted-color); }
.facts dd { margin: 0; }
.photo img { max-width: 100%; max-height: 16rem; display: block; margin-bottom: 0.5rem; border-radius: 6px; }
.actions, .child-print { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; margin: 1rem 0; }
.child-print label { display: grid; gap: 0.25rem; }
</style>
