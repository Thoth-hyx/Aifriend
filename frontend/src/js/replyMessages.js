export function replyBubbles(message) {
  const parts = message.role === 'ai' && message.status === 'completed' && message.reply_parts?.length
    ? message.reply_parts : [message.content]
  return parts.map((content, index) => ({ ...message, content, bubbleKey: `${message.id}:${index}` }))
}

export function updateReply(messages, id, delta) {
  const message = messages.find(message => message.id === id)
  if (message) message.content += delta
}

export function replaceReply(messages, id, parts) {
  const index = messages.findIndex(message => message.id === id)
  if (index < 0) return
  const original = messages[index]
  const count = messages.filter(message => message.id === id || message.reply_id === id).length
  messages.splice(index, count, ...parts.map((content, i) => ({
    ...original, id: i === 0 ? id : `${id}:${i}`, reply_id: id, content,
  })))
}
