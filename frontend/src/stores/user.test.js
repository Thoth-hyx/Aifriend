import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useUserStore } from './user.js'

test('voice cloning capability comes from the server and clears on account changes', () => {
  setActivePinia(createPinia())
  const user = useUserStore()
  assert.equal(user.canCloneVoice, false)
  user.setUserInfo({ user_id: 1, username: 'admin', can_clone_voice: false })
  assert.equal(user.canCloneVoice, false)
  user.setUserInfo({ user_id: 2, username: 'staff', can_clone_voice: true })
  assert.equal(user.canCloneVoice, true)
  user.logout()
  assert.equal(user.canCloneVoice, false)
  user.setUserInfo({ user_id: 2, can_clone_voice: true })
  user.setUserInfo({ user_id: 3 })
  assert.equal(user.canCloneVoice, false)
})
