export function replyBubbles(message) {
  const parts = message.role === 'ai' && message.status === 'completed' && message.reply_parts?.length
    ? message.reply_parts : [message.content]
  return parts.map((content, index) => ({ ...message, content, bubbleKey: `${message.id}:${index}` }))
}

export function appendReplyPart(messages, id, partIndex, delta) {
  if (!Number.isInteger(partIndex) || partIndex < 0 || partIndex > 2 || !delta) return
  const bubbleId = partIndex === 0 ? id : `${id}:${partIndex}`
  const existing = messages.find(message => message.id === bubbleId)
  if (existing) {
    existing.content += delta
    return
  }
  const root = messages.findIndex(message => message.id === id)
  if (root < 0) return
  let index = root + 1
  while (messages[index]?.reply_id === id && messages[index].part_index < partIndex) index++
  messages.splice(index, 0, {
    ...messages[root], id: bubbleId, reply_id: id, part_index: partIndex, content: delta,
  })
}
