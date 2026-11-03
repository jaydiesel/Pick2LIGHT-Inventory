<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import { useSession } from '@/stores/session'

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
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    router.push(next)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not reach the server'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="center">
    <form class="card stack login" @submit.prevent="submit">
      <h1>Pick2LIGHT</h1>
      <div class="field">
        <label for="u">Username</label>
        <input id="u" v-model="username" class="p2l-input" autocomplete="username" data-test="username" />
      </div>
      <div class="field">
        <label for="p">Password</label>
        <input id="p" v-model="password" class="p2l-input" type="password" autocomplete="current-password" data-test="password" />
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="p2l-btn primary" type="submit" :disabled="busy" data-test="login">Log in</button>
    </form>
  </div>
</template>

<style scoped>
.center { min-height: 100vh; display: grid; place-items: center; padding: 1rem; }
.login { width: min(360px, 100%); }
</style>
