import assert from 'node:assert/strict'
import test from 'node:test'
import { voiceUploadError } from '../frontend/src/js/voiceUpload.js'

test('upload accepts supported extensions and rejects missing, oversized or long samples', () => {
  for (const name of ['sample.WAV', 'sample.mp3', 'sample.m4a']) {
    assert.equal(voiceUploadError({ name, size: 1000 }, 15), '')
  }
  assert.ok(voiceUploadError(null))
  assert.ok(voiceUploadError({ name: 'sample.exe', size: 1000 }))
  assert.ok(voiceUploadError({ name: 'sample.wav', size: 0 }))
  assert.ok(voiceUploadError({ name: 'sample.mp3', size: 10 * 1024 * 1024 + 1 }))
  assert.ok(voiceUploadError({ name: 'sample.m4a', size: 1000 }, 61))
  assert.ok(voiceUploadError({ name: 'sample.m4a', size: 1000 }, 4))
})
