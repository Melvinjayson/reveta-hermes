/** Display only explicit HTTP(S) citations; malformed model output must not break the thread. */
export function auraSources(text: string): [string, string][] {
  const sources = new Map<string, string>()

  for (const match of text.matchAll(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g)) {
    try {
      const target = new URL(match[2])

      if (target.hostname && ['http:', 'https:'].includes(target.protocol)) {
        sources.set(match[2], match[1])
      }
    } catch {
      // An invalid citation remains ordinary message text.
    }
  }

  return [...sources.entries()]
}
