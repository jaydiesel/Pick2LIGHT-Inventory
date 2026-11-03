<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError, apiFetch } from '@/api/client'
import type { AuthStatus, PackSummary } from '@/api/types'
import { useSession } from '@/stores/session'

const router = useRouter()
const session = useSession()
const step = ref(1)
const mode = ref<'password' | 'none'>('password')
const username = ref('admin')
const password = ref('')
const confirm = ref('')
const packs = ref<PackSummary[]>([])
const chosen = ref<string[]>([])
const error = ref('')
const busy = ref(false)

const tooShort = computed(() => password.value.length < 8)
const mismatch = computed(() => confirm.value !== '' && confirm.value !== password.value)
const loginValid = computed(
  () => mode.value === 'none' || (!tooShort.value && password.value === confirm.value && username.value.trim() !== ''),
)

onMounted(async () => {
  try {
    packs.value = await apiFetch<PackSummary[]>('/packs')
    chosen.value = packs.value.filter((p) => p.id !== 'generic').map((p) => p.id)
  } catch {
    error.value = 'Could not load the starter packs'
  }
})

async function finish() {
  busy.value = true
  error.value = ''
  const body: Record<string, unknown> =
    mode.value === 'password'
      ? { auth_mode: 'password', username: username.value.trim(), password: password.value, packs: chosen.value }
      : { auth_mode: 'none', packs: chosen.value }
  try {
    session.apply(await apiFetch<AuthStatus>('/setup', { method: 'POST', json: body }))
    router.push('/')
  } catch (e) {
    error.value = e instanceof ApiError ? Object.values(e.fields)[0] || e.message : 'Setup failed'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <div class="card stack setup">
      <h1>Welcome to Pick2LIGHT</h1>
      <p class="muted">Step {{ step }} of 3</p>

      <template v-if="step === 1">
        <h2>Login</h2>
        <div class="row">
          <button :class="['p2l-btn', { primary: mode === 'password' }]" data-test="mode-password" @click="mode = 'password'">
            Use a password
          </button>
          <button :class="['p2l-btn', { primary: mode === 'none' }]" data-test="mode-none" @click="mode = 'none'">
            No login (trusted home network)
          </button>
        </div>
        <template v-if="mode === 'password'">
          <div class="field">
            <label for="su">Username</label>
            <input id="su" v-model="username" class="p2l-input" data-test="username" />
          </div>
          <div class="field">
            <label for="sp">Password</label>
            <input id="sp" v-model="password" class="p2l-input" type="password" autocomplete="new-password" data-test="password" />
            <span v-if="tooShort" class="muted">At least 8 characters</span>
          </div>
          <div class="field">
            <label for="sc">Confirm password</label>
            <input id="sc" v-model="confirm" class="p2l-input" type="password" autocomplete="new-password" data-test="confirm" />
            <span v-if="mismatch" class="error">Passwords don't match</span>
          </div>
        </template>
        <div class="row">
          <span class="spacer" />
          <button class="p2l-btn primary" :disabled="!loginValid" data-test="next" @click="step = 2">Next</button>
        </div>
      </template>

      <template v-else-if="step === 2">
        <h2>Starter categories</h2>
        <p class="muted">Pick ready-made categories with fields. You can change or delete them later.</p>
        <label v-for="p in packs" :key="p.id" class="pack">
          <input v-model="chosen" type="checkbox" :value="p.id" :data-test="`pack-${p.id}`" />
          <span><b>{{ p.name }}</b> <span class="muted">— {{ p.description }}</span></span>
        </label>
        <div class="row">
          <button class="p2l-btn" @click="step = 1">Back</button>
          <span class="spacer" />
          <button class="p2l-btn primary" data-test="next" @click="step = 3">Next</button>
        </div>
      </template>

      <template v-else>
        <h2>Ready</h2>
        <p>
          Login: <b>{{ mode === 'password' ? `password for ${username}` : 'none' }}</b><br />
          Starter packs: <b>{{ chosen.length ? packs.filter((p) => chosen.includes(p.id)).map((p) => p.name).join(', ') : 'none' }}</b>
        </p>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <div class="row">
          <button class="p2l-btn" @click="step = 2">Back</button>
          <span class="spacer" />
          <button class="p2l-btn primary" :disabled="busy" data-test="finish" @click="finish">Finish setup</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.wrap { min-height: 100vh; display: grid; place-items: center; padding: 1rem; }
.setup { width: min(560px, 100%); }
.pack { display: flex; gap: .6rem; align-items: flex-start; padding: .4rem 0; }
</style>
