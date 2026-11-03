import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'

export default defineConfigWithVueTs(
  { name: 'app/files', files: ['**/*.{ts,mts,vue}'] },
  { ignores: ['dist/**', 'src/api/schema.d.ts', 'playwright-report/**', 'test-results/**', 'openapi.json'] },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  { files: ['src/views/**/*.vue'], rules: { 'vue/multi-word-component-names': 'off' } },
)
