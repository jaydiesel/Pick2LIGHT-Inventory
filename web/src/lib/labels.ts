import { apiBlob, apiFetch, openBlob } from '@/api/client'
import type { LabelTemplateOut } from '@/api/types'

export type LabelTarget = 'item' | 'unit' | 'location'

/** Templates for a target; the one named after the target ("Unit 30×15") comes first as the default. */
export async function templatesFor(target: LabelTarget): Promise<LabelTemplateOut[]> {
  const prefix = target[0].toUpperCase() + target.slice(1)
  const list = (await apiFetch<LabelTemplateOut[]>('/label-templates')).filter((t) => t.target === target)
  return [...list.filter((t) => t.name.startsWith(prefix)), ...list.filter((t) => !t.name.startsWith(prefix))]
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
