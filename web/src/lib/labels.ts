import { apiBlob, apiFetch, openBlob } from '@/api/client'
import type { LabelTemplateOut } from '@/api/types'

export type LabelTarget = 'item' | 'unit' | 'location'

export async function templatesFor(target: LabelTarget): Promise<LabelTemplateOut[]> {
  return (await apiFetch<LabelTemplateOut[]>('/label-templates')).filter((t) => t.target === target)
}

/** Render labels to a PDF and open it in a new tab (print from the browser). */
export async function printLabels(
  target: LabelTarget,
  ids: number[],
  opts: { templateId?: number; copies?: number; sheetId?: string | null; startPosition?: number } = {},
): Promise<void> {
  const templateId = opts.templateId ?? (await templatesFor(target))[0]?.id
  if (!templateId) throw new Error(`No ${target} label template — add one under Labels`)
  const blob = await apiBlob('/labels/pdf', {
    method: 'POST',
    json: {
      template_id: templateId,
      target_type: target,
      ids,
      copies: opts.copies ?? 1,
      sheet_id: opts.sheetId || null,
      start_position: opts.startPosition ?? 0,
    },
  })
  openBlob(blob)
}
