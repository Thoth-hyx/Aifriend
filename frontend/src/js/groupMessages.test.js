import assert from 'node:assert/strict'
import test from 'node:test'
import { mergeMessages } from './groupMessages.js'

test('reconnect updates an existing reply without duplicates or stale rollback', () => {
  const old = [{ id: 1, revision: 1, content: '问题' }, { id: 2, revision: 2, content: '' }]
  const completed = { id: 2, revision: 5, content: '完整回复', status: 'completed' }
  const merged = mergeMessages(old, [completed, { id: 2, revision: 3, content: '部分' }])
  assert.equal(merged.length, 2)
  assert.equal(merged[1].content, '完整回复')
})

test('lost send acknowledgement reconciles optimistic message by client id', () => {
  const current = [{ id: 'local:abc', client_message_id: 'abc', status: 'failed', revision: 0 }]
  const persisted = { id: 7, client_message_id: 'abc', status: 'completed', revision: 1 }
  assert.deepEqual(mergeMessages(current, [persisted, persisted]), [persisted])
  assert.deepEqual(mergeMessages([persisted], current), [persisted])
})
