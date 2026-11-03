<script setup lang="ts">
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import RadioButton from 'primevue/radiobutton'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, apiFetch } from '../api/client'
import { useSession } from '../stores/session'
import { useSettings } from '../stores/settings'

interface Pack {
  id: string
  name: string
  description: string
  category_count: number
}

const MIN_PASSWORD = 8

const router = useRouter()
const step = ref(1)
const authMode = ref<'password' | 'none'>('password')
const username = ref('admin')
const password = ref('')
const confirm = ref('')
const packs = ref<Pack[]>([])
const chosen = ref<string[]>([])
const error = ref('')
const busy = ref(false)

onMounted(async () => {
  try {
    packs.value = await apiFetch<Pack[]>('/packs')
    chosen.value = packs.value.filter((p) => p.id !== 'generic').map((p) => p.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load starter packs'
  }
})

const passwordTooShort = computed(() => password.value.length < MIN_PASSWORD)
const mismatch = computed(() => confirm.value !== '' && confirm.value !== password.value)
const step1Valid = computed(
  () =>
    authMode.value === 'none' ||
    (username.value.trim() !== '' && !passwordTooShort.value && confirm.value === password.value),
)

async function finish() {
  busy.value = true
  error.value = ''
  try {
    await apiFetch('/setup', {
      method: 'POST',
      json: {
        auth_mode: authMode.value,
        username: username.value.trim() || 'admin',
        ...(authMode.value === 'password' ? { password: password.value } : {}),
        packs: chosen.value,
      },
    })
    await useSession().load()
    await useSettings().load()
    await router.push('/')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not reach the server'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-card">
    <h1>Welcome to Pick2LIGHT Inventory</h1>
    <p class="muted">Step {{ step }} of 3</p>

    <section v-if="step === 1">
      <h2>Login</h2>
      <label class="choice">
        <RadioButton v-model="authMode" value="password" name="auth" />
        Require a password
      </label>
      <label class="choice">
        <RadioButton v-model="authMode" value="none" name="auth" />
        No login (trusted network only)
      </label>
      <template v-if="authMode === 'password'">
        <label>
          Username
          <InputText v-model="username" autocomplete="username" fluid />
        </label>
        <label>
          Password
          <Password v-model="password" :feedback="false" autocomplete="new-password" fluid />
        </label>
        <small v-if="password !== '' && passwordTooShort" class="error">At least {{ MIN_PASSWORD }} characters</small>
        <label>
          Confirm password
          <Password v-model="confirm" :feedback="false" autocomplete="new-password" fluid />
        </label>
        <small v-if="mismatch" class="error">Passwords do not match</small>
      </template>
    </section>

    <section v-else-if="step === 2">
      <h2>Starter packs</h2>
      <p class="muted">Categories and fields to start from. All optional.</p>
      <label v-for="p in packs" :key="p.id" class="choice">
        <Checkbox v-model="chosen" :value="p.id" />
        <span>
          <strong>{{ p.name }}</strong> ({{ p.category_count }} categories)<br />
          <small class="muted">{{ p.description }}</small>
        </span>
      </label>
    </section>

    <section v-else>
      <h2>Ready</h2>
      <ul>
        <li>{{ authMode === 'password' ? `Password login as ${username}` : 'No login' }}</li>
        <li>{{ chosen.length }} starter pack(s)</li>
      </ul>
    </section>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <div class="wizard-actions">
      <Button v-if="step > 1" label="Back" severity="secondary" :disabled="busy" @click="step--" />
      <Button v-if="step < 3" data-test="next" label="Next" :disabled="step === 1 && !step1Valid" @click="step++" />
      <Button v-else data-test="finish" label="Finish" :loading="busy" @click="finish" />
    </div>
  </main>
</template>
