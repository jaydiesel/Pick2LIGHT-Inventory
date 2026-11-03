/** Turn a label into a field key matching ^[a-z][a-z0-9_]{0,62}$ (server KEY_RE). */
export function slugKey(label: string): string {
  let s = label
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (s && !/^[a-z]/.test(s)) s = `f_${s}`
  return s.slice(0, 63)
}

export const KEY_RE = /^[a-z][a-z0-9_]{0,62}$/

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}
