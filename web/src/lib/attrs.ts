/**
 * Build the attrs/values patch a form should send: only keys that still have a field definition
 * and whose value changed; cleared fields are sent as null. Values of removed fields are never
 * sent, so an item stays editable after its category's fields change (spec §3.5).
 */
export function attrsPatch(
  original: Record<string, unknown>,
  current: Record<string, unknown>,
  keys: string[],
): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  for (const key of keys) {
    const had = key in original
    const has = key in current && current[key] !== null && current[key] !== undefined
    if (has && JSON.stringify(current[key]) !== JSON.stringify(original[key])) patch[key] = current[key]
    else if (!has && had) patch[key] = null
  }
  return patch
}
