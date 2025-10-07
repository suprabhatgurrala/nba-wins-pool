<script setup lang="ts">
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'

const props = withDefaults(
  defineProps<{
    visible: boolean
    title?: string
    message?: string
    confirmLabel?: string
    cancelLabel?: string
    confirmSeverity?:
      | 'primary'
      | 'secondary'
      | 'success'
      | 'info'
      | 'warning'
      | 'help'
      | 'danger'
      | 'contrast'
    confirmIcon?: string
    confirmLoading?: boolean
    confirmDisabled?: boolean
    dialogClass?: string
  }>(),
  {
    title: 'Confirm Delete',
    message: 'Are you sure you want to delete this item? This action cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    confirmSeverity: 'danger',
    confirmIcon: 'pi pi-trash',
    confirmLoading: false,
    confirmDisabled: false,
    dialogClass: 'container min-w-min max-w-md mx-4',
  },
)

const emit = defineEmits<{
  (event: 'update:visible', value: boolean): void
  (event: 'confirm'): void
  (event: 'cancel'): void
}>()

const onVisibleChange = (value: boolean) => {
  emit('update:visible', value)
}

const handleCancel = () => {
  emit('cancel')
  emit('update:visible', false)
}

const handleConfirm = () => {
  emit('confirm')
}
</script>

<template>
  <Dialog
    :visible="props.visible"
    modal
    :draggable="false"
    dismissableMask
    :class="props.dialogClass"
    @update:visible="onVisibleChange"
  >
    <template #header>
      <p class="text-xl font-semibold">{{ props.title }}</p>
    </template>
    <div class="flex flex-col gap-4">
      <slot name="message">
        <p class="text-sm text-surface-500">{{ props.message }}</p>
      </slot>
      <div class="flex justify-end gap-2">
        <Button :label="props.cancelLabel" severity="secondary" variant="outlined" @click="handleCancel" />
        <Button
          :label="props.confirmLabel"
          :severity="props.confirmSeverity"
          :icon="props.confirmIcon"
          :loading="props.confirmLoading"
          :disabled="props.confirmDisabled"
          @click="handleConfirm"
        />
      </div>
    </div>
  </Dialog>
</template>
