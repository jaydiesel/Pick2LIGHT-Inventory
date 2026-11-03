import Aura from '@primevue/themes/aura'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import 'primeicons/primeicons.css'
import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { useSettings } from './stores/settings'
import { useSession } from './stores/session'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(PrimeVue, {
  theme: { preset: Aura, options: { darkModeSelector: '.app-dark' } },
})
app.use(ToastService)
app.use(router)

// Router guard has loaded the session; settings need it (full set only when authenticated).
router.isReady().then(async () => {
  if (useSession().setupCompleted) await useSettings().load().catch(() => {})
})

app.mount('#app')
