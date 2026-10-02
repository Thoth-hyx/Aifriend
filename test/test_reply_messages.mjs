import assert from 'node:assert/strict'
import test from 'node:test'
import { replyBubbles, replaceReply, updateReply } from '../frontend/src/js/replyMessages.js'
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

test('private replies target their own placeholder and repeated completion is idempotent', () => {
  const messages = [{ id: 'a', role: 'ai', content: '' }, { id: 'u', role: 'user', content: '新问题' }, { id: 'b', role: 'ai', content: '' }]
  updateReply(messages, 'a', '旧问题的回答')
  assert.equal(messages[2].content, '')
  for (let i = 0; i < 2; i++) replaceReply(messages, 'a', ['第一条', '第二条', '第三条'])
  assert.deepEqual(messages.map(m => m.content), ['第一条', '第二条', '第三条', '新问题', ''])
  replaceReply(messages, 'missing', ['忽略'])
  assert.equal(messages.length, 5)
})
