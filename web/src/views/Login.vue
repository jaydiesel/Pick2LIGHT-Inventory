<script setup lang="ts">
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { useSession } from '../stores/session'

const session = useSession()
const router = useRouter()
const route = useRoute()

const username = ref('admin')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = ''
  try {
    await session.login(username.value, password.value)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    await router.push(next.startsWith('/') && !next.startsWith('//') ? next : '/')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not reach the server'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-card">
    <h1>Pick2LIGHT Inventory</h1>
    <form @submit.prevent="submit">
      <label>
        Username
        <InputText v-model="username" autocomplete="username" fluid />
      </label>
      <label>
        Password
        <Password v-model="password" :feedback="false" autocomplete="current-password" fluid />
      </label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <Button type="submit" label="Log in" :loading="busy" :disabled="!password" />
    </form>
  </main>
</template>
