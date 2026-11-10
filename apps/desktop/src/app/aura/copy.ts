const cache = new WeakMap<object, unknown>()

/** Product copy only: wire IDs, translation keys and lowercase CLI commands stay intact. */
export function auraCopy<T>(value: T): T {
  if (typeof value === 'string') {
    return value
      .replace(/\bHermes by Nous Research\b/g, 'Aura by Reveta')
      .replace(/\b(?:NOUSRESEARCH|Nous Research|Nous|Hermes)\b/g, 'Aura') as T
  }

  if (typeof value === 'function') {
    return ((...args: unknown[]) => auraCopy(value(...args))) as T
  }

  if (value && typeof value === 'object') {
    if (cache.has(value)) {
      return cache.get(value) as T
    }

    const copy = Array.isArray(value)
      ? value.map(item => auraCopy(item))
      : Object.fromEntries(Object.entries(value).map(([key, item]) => [key, auraCopy(item)]))

    cache.set(value, copy)

    return copy as T
  }

  return value
}
