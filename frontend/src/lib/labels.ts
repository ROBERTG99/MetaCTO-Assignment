// Display labels shared by components.

/** "claude-haiku-4-5-20251001" -> "Haiku 4.5"; the offline path says so plainly. */
export function sourceLabel(model: string | null | undefined): string {
  if (!model) return 'AI'
  if (model.startsWith('offline')) return 'Offline baseline'
  const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(model)
  if (!m) return model
  const [, family = '', major, minor] = m
  return `${family.charAt(0).toUpperCase()}${family.slice(1)} ${major}.${minor}`
}
