import 'primeicons/primeicons.css'
import './style.css'

import Aura from '@primeuix/themes/aura'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ConfirmationService from 'primevue/confirmationservice'
import ToastService from 'primevue/toastservice'
import { createApp } from 'vue'

import { setUnauthenticatedHandler } from '@/api/client'
import App from '@/App.vue'
import { router } from '@/router'
import { useSession } from '@/stores/session'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(PrimeVue, { theme: { preset: Aura, options: { darkModeSelector: '.p2l-dark' } } })
app.use(ToastService)
app.use(ConfirmationService)

setUnauthenticatedHandler(() => {
  useSession(pinia).onUnauthenticated()
  const current = router.currentRoute.value
  if (current.name !== 'login') router.push({ name: 'login', query: { next: current.fullPath } })
})

app.mount('#app')
