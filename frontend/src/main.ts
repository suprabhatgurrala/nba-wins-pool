import './assets/main.css'
import 'primeicons/primeicons.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import ConfirmationService from 'primevue/confirmationservice'
import Aura from '@primevue/themes/aura'
import { definePreset } from '@primevue/themes'
import App from './App.vue'
import router from './router'
import Tooltip from 'primevue/tooltip'

const app = createApp(App)

const customPreset = definePreset(Aura, {})

app.use(PrimeVue, {
  theme: {
    preset: customPreset,
    options: {
      darkModeSelector: '.dark-mode-always',
      cssLayer: {
        name: 'primevue',
        order: 'theme, base, primevue',
      },
    },
  },
})
app.use(ToastService)
app.use(ConfirmationService)
app.use(createPinia())
app.use(router)
// https://primevue.org/tooltip/
app.directive('tooltip', Tooltip)

app.mount('#app')
