import assert from 'node:assert/strict'
import test from 'node:test'
import { replyBubbles, appendReplyPart } from '../frontend/src/js/replyMessages.js'
import { mergeMessages } from '../frontend/src/js/groupMessages.js'

test('completed group replies show separate bubbles, partial replies stay in one bubble', () => {
  const reply = { id: 2, role: 'ai', status: 'completed', content: '甲。乙。丙。', reply_parts: ['甲。', '乙。', '丙。'] }
  assert.deepEqual(replyBubbles(reply).map(m => m.content), reply.reply_parts)
  assert.equal(new Set(replyBubbles(reply).map(m => m.bubbleKey)).size, 3)
  assert.equal(replyBubbles({ ...reply, status: 'generating' }).length, 1)
  assert.equal(replyBubbles({ ...reply, role: 'user' }).length, 1)
  const recovered = mergeMessages([reply], [reply, { ...reply, revision: -1, reply_parts: ['旧回复'] }])
  assert.equal(recovered.length, 1)
  assert.equal(replyBubbles(recovered[0]).length, 3)
})

test('private streaming replies append stable bubbles beside their own placeholder', () => {
  const messages = [{ id: 'a', role: 'ai', content: '' }, { id: 'u', role: 'user', content: '新问题' }, { id: 'b', role: 'ai', content: '' }]
  const firstBubble = messages[0]
  appendReplyPart(messages, 'a', 0, '第一条。')
  assert.equal(messages[2].content, '')
  appendReplyPart(messages, 'a', 1, '第二')
  const secondBubble = messages[1]
  assert.strictEqual(messages[0], firstBubble)
  assert.equal(firstBubble.content, '第一条。')
  appendReplyPart(messages, 'a', 1, '条。')
  assert.strictEqual(messages[1], secondBubble)
  appendReplyPart(messages, 'a', 2, '第三条。第四条。')
  assert.deepEqual(messages.map(m => m.content), ['第一条。', '第二条。', '第三条。第四条。', '新问题', ''])
  assert.deepEqual(messages.map(m => m.id), ['a', 'a:1', 'a:2', 'u', 'b'])
  for (const invalid of [-1, 3, null, '1']) appendReplyPart(messages, 'a', invalid, '忽略')
  appendReplyPart(messages, 'missing', 1, '忽略')
  assert.equal(messages.length, 5)
})
