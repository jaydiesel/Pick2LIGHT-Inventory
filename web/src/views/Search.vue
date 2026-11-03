<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { CategoryOut, FieldDefOut, LocationOut, LogEntryTypeOut, SearchPage } from '@/api/types'
import LocationPicker from '@/components/LocationPicker.vue'
import { type SearchState, queryToState, stateToQuery, stateToSearchBody } from '@/lib/searchQuery'

const PAGE = 50
const route = useRoute()
const router = useRouter()
const state = reactive<SearchState>(queryToState(route.query))
const page = ref<SearchPage | null>(null)
const categories = ref<CategoryOut[]>([])
const fields = ref<FieldDefOut[]>([])
const logTypes = ref<LogEntryTypeOut[]>([])
const locationName = ref('')
const picking = ref(false)
const error = ref('')
const CONDITIONS = [['new', 'New'], ['tested_good', 'Tested good'], ['untested', 'Untested'], ['faulty', 'Faulty'], ['for_parts', 'For parts']]
const OPS = [['eq', '='], ['ne', '≠'], ['lt', '<'], ['lte', '≤'], ['gt', '>'], ['gte', '≥'], ['contains', 'contains']]

const filterable = computed(() => fields.value.filter((f) => f.filterable))
const latestFields = computed(() =>
  logTypes.value.flatMap((t) =>
    (t.summary_fields ?? []).map((k) => ({ log_type: t.key, key: k, label: `${t.name}: ${(t.fields.find((f) => f.key === k)?.label as string) ?? k}` })),
  ),
)

async function loadCategoryMeta() {
  if (state.category === null) {
    fields.value = []
    logTypes.value = []
    return
  }
  ;[fields.value, logTypes.value] = await Promise.all([
    apiFetch<FieldDefOut[]>(`/categories/${state.category}/fields`),
    apiFetch<LogEntryTypeOut[]>(`/categories/${state.category}/log-types`),
  ])
}

async function run() {
  error.value = ''
  try {
    page.value = await apiFetch<SearchPage>('/search', { method: 'POST', json: stateToSearchBody(state, PAGE) })
  } catch (e) {
    error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : String(e)
  }
}

function apply(resetPage = true) {
  if (resetPage) state.page = 0
  router.replace({ name: 'search', query: stateToQuery(state) })
}

watch(
  () => route.query,
  async (q) => {
    Object.assign(state, queryToState(q))
    await run()
  },
)
watch(() => state.category, loadCategoryMeta)
watch(
  () => state.location,
  async (id) => {
    locationName.value = id === null ? '' : (await apiFetch<LocationOut>(`/locations/${id}`)).path.map((p) => p.name).join(' › ')
  },
  { immediate: true },
)

function toggleCondition(c: string) {
  state.conditions = state.conditions.includes(c) ? state.conditions.filter((x) => x !== c) : [...state.conditions, c]
  apply()
}

function chooseLocation(id: number) {
  picking.value = false
  state.location = id
  apply()
}

onMounted(async () => {
  categories.value = await apiFetch<CategoryOut[]>('/categories')
  await loadCategoryMeta()
  await run()
})
</script>

<template>
  <h1>Search</h1>
  <form class="card stack" @submit.prevent="apply()">
    <div class="row">
      <input v-model="state.q" class="p2l-input spacer" data-scan-target placeholder="Name, SKU, value (4k7, 10uF)…" data-test="q" />
      <button class="p2l-btn primary" type="submit">Search</button>
    </div>
    <div class="row">
      <select v-model="state.category" class="p2l-input" data-test="category" @change="apply()">
        <option :value="null">All categories</option>
        <option v-for="c in categories" :key="c.id" :value="c.id">{{ c.path.map((p) => p.name).join(' › ') }}</option>
      </select>
      <label class="row"><input v-model="state.sub" type="checkbox" @change="apply()" /> include subcategories</label>
      <button class="p2l-btn" type="button" @click="picking = true"><i class="pi pi-map-marker" /> {{ locationName || 'Any location' }}</button>
      <button v-if="state.location !== null" class="p2l-btn" type="button" @click="state.location = null; apply()">×</button>
      <label class="row"><input v-model="state.low" type="checkbox" @change="apply()" /> low stock only</label>
    </div>
    <div class="row">
      <span class="muted">Condition:</span>
      <button
        v-for="[c, label] in CONDITIONS"
        :key="c"
        type="button"
        :class="['p2l-btn', { primary: state.conditions.includes(c) }]"
        @click="toggleCondition(c)"
      >
        {{ label }}
      </button>
    </div>
    <div v-if="filterable.length || latestFields.length" class="stack">
      <div v-for="(f, i) in state.filters" :key="`f${i}`" class="row">
        <select v-model="f.key" class="p2l-input">
          <option v-for="s in filterable" :key="s.key" :value="s.key">{{ s.label }}</option>
        </select>
        <select v-model="f.op" class="p2l-input"><option v-for="[o, l] in OPS" :key="o" :value="o">{{ l }}</option></select>
        <input v-model="f.value" class="p2l-input" placeholder="value, e.g. 5k" />
        <button class="p2l-btn" type="button" @click="state.filters.splice(i, 1); apply()">×</button>
      </div>
      <div v-for="(f, i) in state.latest" :key="`l${i}`" class="row">
        <select
          :value="`${f.log_type}.${f.key}`"
          class="p2l-input"
          @change="(e) => { const [t, k] = (e.target as HTMLSelectElement).value.split('.'); f.log_type = t; f.key = k }"
        >
          <option v-for="l in latestFields" :key="`${l.log_type}.${l.key}`" :value="`${l.log_type}.${l.key}`">Latest {{ l.label }}</option>
        </select>
        <select v-model="f.op" class="p2l-input"><option v-for="[o, l] in OPS" :key="o" :value="o">{{ l }}</option></select>
        <input v-model="f.value" class="p2l-input" placeholder="value" />
        <button class="p2l-btn" type="button" @click="state.latest.splice(i, 1); apply()">×</button>
      </div>
      <div class="row">
        <button v-if="filterable.length" class="p2l-btn" type="button" @click="state.filters.push({ key: filterable[0].key, op: 'eq', value: '' })">+ Field filter</button>
        <button
          v-if="latestFields.length"
          class="p2l-btn"
          type="button"
          @click="state.latest.push({ log_type: latestFields[0].log_type, key: latestFields[0].key, op: 'lt', value: '' })"
        >
          + Latest test value
        </button>
      </div>
    </div>
  </form>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <section v-if="page" class="card">
    <p v-if="page.location_match">
      Location: <RouterLink :to="`/locations/${page.location_match.id}`">{{ page.location_match.name }}</RouterLink>
    </p>
    <p class="muted">{{ page.total }} result{{ page.total === 1 ? '' : 's' }}</p>
    <table v-if="page.hits.length" class="plain" data-test="results">
      <thead><tr><th>Name</th><th>SKU</th><th>Category</th><th>On hand</th><th>Details</th></tr></thead>
      <tbody>
        <tr v-for="h in page.hits" :key="h.id">
          <td>
            <RouterLink :to="h.matched_unit_id ? `/units/${h.matched_unit_id}` : `/items/${h.id}`">{{ h.name }}</RouterLink>
            <span v-if="h.min_stock !== null && h.on_hand < h.min_stock" class="badge warn">low</span>
          </td>
          <td>{{ h.sku }}</td>
          <td>{{ h.category_name }}</td>
          <td>{{ h.on_hand }}</td>
          <td class="muted">{{ Object.values(h.attrs_display).slice(0, 4).join(' · ') }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="page.total > PAGE" class="row">
      <button class="p2l-btn" :disabled="state.page === 0" @click="state.page--; apply(false)">Previous</button>
      <span class="muted">Page {{ state.page + 1 }} of {{ Math.ceil(page.total / PAGE) }}</span>
      <button class="p2l-btn" :disabled="(state.page + 1) * PAGE >= page.total" @click="state.page++; apply(false)">Next</button>
    </div>
  </section>
  <LocationPicker :open="picking" title="Search in location" @select="chooseLocation" @close="picking = false" />
</template>
