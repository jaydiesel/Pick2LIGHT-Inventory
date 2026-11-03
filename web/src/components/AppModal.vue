<script setup lang="ts">
defineProps<{ open: boolean; title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <div v-if="open" class="overlay" role="dialog" aria-modal="true" :aria-label="title" @click.self="emit('close')" @keydown.esc="emit('close')">
    <div :class="['dialog', 'card', { wide }]">
      <div class="row head">
        <h2>{{ title }}</h2>
        <span class="spacer" />
        <button class="p2l-btn" aria-label="Close" data-test="modal-close" @click="emit('close')"><i class="pi pi-times" /></button>
      </div>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.overlay { position: fixed; inset: 0; background: rgba(0, 0, 0, .45); display: grid; place-items: center; z-index: 50; padding: 1rem; }
.dialog { width: min(480px, 100%); max-height: 85vh; overflow: auto; margin: 0; }
.dialog.wide { width: min(820px, 100%); }
.head { margin-bottom: .5rem; }
</style>
