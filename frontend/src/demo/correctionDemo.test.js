import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  DEMO_ATTEMPT_1_ANSWER,
  DEMO_ATTEMPT_2_ANSWER,
  DEMO_CORRECTION_QUERY,
  DEMO_QUESTION,
  DEMO_TOPICS,
  coversAllDemoTopics,
  missingDemoTopics,
  topicsCovered,
} from './correctionDemo.js'

describe('Correction Demo topic coverage', () => {
  it('uses a fixed question that names all three topics', () => {
    assert.equal(
      DEMO_QUESTION,
      'Explain network segmentation, MFA, and centralized logging, including one limitation of each.',
    )
    assert.deepEqual(topicsCovered(DEMO_QUESTION), [
      'segmentation',
      'mfa',
      'logging',
    ])
  })

  it('scripts Attempt 1 to miss MFA and logging', () => {
    assert.ok(topicsCovered(DEMO_ATTEMPT_1_ANSWER).includes('segmentation'))
    assert.deepEqual(missingDemoTopics(DEMO_ATTEMPT_1_ANSWER).sort(), [
      'logging',
      'mfa',
    ])
    assert.equal(coversAllDemoTopics(DEMO_ATTEMPT_1_ANSWER), false)
  })

  it('keeps all three topics in the rewritten correction query', () => {
    assert.equal(coversAllDemoTopics(DEMO_CORRECTION_QUERY), true)
    assert.deepEqual(
      topicsCovered(DEMO_CORRECTION_QUERY).sort(),
      DEMO_TOPICS.map((topic) => topic.id).sort(),
    )
  })

  it('covers all three topics in the second answer', () => {
    assert.equal(coversAllDemoTopics(DEMO_ATTEMPT_2_ANSWER), true)
    assert.deepEqual(missingDemoTopics(DEMO_ATTEMPT_2_ANSWER), [])
  })
})
