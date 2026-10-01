export function mergeMessages(current, incoming) {
  const messages = new Map(current.map(message => [message.id, message]))
  for (const message of incoming) {
    if (message.client_message_id) {
      if (typeof message.id !== 'number' && [...messages.values()].some(existing =>
        typeof existing.id === 'number' && existing.client_message_id === message.client_message_id)) continue
      for (const [id, existing] of messages) {
        if (id !== message.id && existing.client_message_id === message.client_message_id) messages.delete(id)
      }
    }
    const existing = messages.get(message.id)
    if (!existing || (message.revision ?? 0) >= (existing.revision ?? 0)) messages.set(message.id, message)
  }
  return [...messages.values()].sort((a, b) => {
    if (typeof a.id === 'number' && typeof b.id === 'number') return a.id - b.id
    if (typeof a.id === 'number') return -1
    if (typeof b.id === 'number') return 1
    return (a.create_time ?? '').localeCompare(b.create_time ?? '')
  })
}
