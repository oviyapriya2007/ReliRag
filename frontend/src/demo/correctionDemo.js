/**
 * Scripted Correction Demo for RELI-RAG.
 *
 * All results are DEMO / SIMULATED. They never call Claude, never hit the API,
 * and never write to the database. Production Ask /query remains unchanged.
 */

export const DEMO_SOURCE_DOCUMENT =
  'RELIRAG_Network_Security_Benchmark.pdf'

export const DEMO_QUESTION =
  'Explain network segmentation, MFA, and centralized logging, including one limitation of each.'

/** Topics the fixed demo question requires. */
export const DEMO_TOPICS = [
  {
    id: 'segmentation',
    label: 'Network segmentation',
    patterns: [/\bnetwork segmentation\b/i, /\bsegmentation\b/i],
  },
  {
    id: 'mfa',
    label: 'MFA',
    patterns: [/\bMFA\b/, /\bmulti-factor authentication\b/i],
  },
  {
    id: 'logging',
    label: 'Centralized logging',
    patterns: [
      /\bcentralized (collection|logging)\b/i,
      /\blogging and monitoring\b/i,
      /\bcentralized logging\b/i,
    ],
  },
]

/**
 * Correction rewrite: keeps all three topics explicit so Attempt 2 can retrieve
 * and answer them. Scripted only — not produced by the live corrector.
 */
export const DEMO_CORRECTION_QUERY =
  'Explain network segmentation (including that it does not replace endpoint security, identity controls, patching, or monitoring), multi-factor authentication / MFA (including that phishing-resistant methods are stronger than one-time codes), and centralized logging / monitoring (including that noisy alerts can hide important events).'

/**
 * Attempt 1 answer: covers segmentation only; intentionally omits MFA and logging.
 */
export const DEMO_ATTEMPT_1_ANSWER = `[DEMO / SIMULATED]

Network segmentation limits unnecessary communication between user devices, servers, management interfaces, and guest systems [1]. VLANs provide Layer 2 separation, while routing and firewall rules enforce communication policy between segments [1]. Segmentation can reduce lateral movement, but it does not replace endpoint security, identity controls, patching, or monitoring [1].`

/**
 * Attempt 2 answer: covers all three topics with evidence markers.
 */
export const DEMO_ATTEMPT_2_ANSWER = `[DEMO / SIMULATED]

Network segmentation limits unnecessary communication between user devices, servers, management interfaces, and guest systems [1]. VLANs provide Layer 2 separation, while routing and firewall rules enforce policy between segments [1]. Limitation: segmentation can reduce lateral movement but does not replace endpoint security, identity controls, patching, or monitoring [1].

Multi-factor authentication (MFA) combines different factor types such as knowledge, possession, and inherence, and reduces risk from stolen passwords [2]. Limitation: phishing-resistant methods provide stronger protection than one-time codes in many threat scenarios [2].

Centralized logging collects relevant events with reliable timestamps so teams can correlate activity across endpoints, servers, identity systems, and network devices [3]. Monitoring should define alert thresholds, ownership, retention, access controls, and escalation procedures [3]. Limitation: excessive noisy alerts can hide important events [3].`

export const DEMO_ATTEMPT_1_EVALUATION = {
  faithfulness: 1.0,
  answer_relevance: 0.5,
  context_relevance: 0.85,
  passed: false,
  failure_type: 'missing_info',
  feedback:
    '[DEMO / SIMULATED] The answer addresses network segmentation and its limitation, but omits MFA and centralized logging that the question explicitly requested.',
  claims: [
    {
      claim_text:
        'Network segmentation limits unnecessary communication between systems.',
      verdict: 'supported',
      evidence_chunk_id: 1401,
      evidence_quote:
        'Segmentation limits unnecessary communication between user devices, servers, management interfaces, and guest systems.',
    },
    {
      claim_text:
        'Segmentation does not replace endpoint security, identity controls, patching, or monitoring.',
      verdict: 'supported',
      evidence_chunk_id: 1401,
      evidence_quote:
        'Segmentation can reduce lateral movement but does not replace endpoint security, identity controls, patching, or monitoring.',
    },
  ],
}

export const DEMO_ATTEMPT_2_EVALUATION = {
  faithfulness: 1.0,
  answer_relevance: 1.0,
  context_relevance: 0.95,
  passed: true,
  failure_type: null,
  feedback:
    '[DEMO / SIMULATED] The corrected answer covers network segmentation, MFA, and centralized logging, states one limitation for each, and stays within the cited passages.',
  claims: [
    {
      claim_text:
        'Network segmentation limits unnecessary communication between systems.',
      verdict: 'supported',
      evidence_chunk_id: 1401,
      evidence_quote:
        'Segmentation limits unnecessary communication between user devices, servers, management interfaces, and guest systems.',
    },
    {
      claim_text:
        'MFA reduces risk from stolen passwords.',
      verdict: 'supported',
      evidence_chunk_id: 1701,
      evidence_quote: 'MFA reduces risk from stolen passwords',
    },
    {
      claim_text:
        'Centralized collection helps correlate events across systems.',
      verdict: 'supported',
      evidence_chunk_id: 2301,
      evidence_quote:
        'Centralized collection helps correlate events across endpoints, servers, identity systems, and network devices.',
    },
  ],
}

export const DEMO_EVIDENCE = [
  {
    rank: 1,
    chunk_id: 1401,
    filename: DEMO_SOURCE_DOCUMENT,
    page_number: 15,
    similarity: 0.91,
    content:
      '[DEMO / SIMULATED excerpt] Segmentation limits unnecessary communication between user devices, servers, management interfaces, and guest systems. VLANs provide Layer 2 separation, while routing and firewall rules enforce communication policy between segments. Segmentation can reduce lateral movement but does not replace endpoint security, identity controls, patching, or monitoring.',
  },
  {
    rank: 2,
    chunk_id: 1701,
    filename: DEMO_SOURCE_DOCUMENT,
    page_number: 18,
    similarity: 0.88,
    content:
      '[DEMO / SIMULATED excerpt] Authentication verifies identity; authorization determines what an authenticated identity may do. Multi-factor authentication combines different factor types, such as knowledge, possession, and inherence. MFA reduces risk from stolen passwords, although phishing-resistant methods provide stronger protection than one-time codes in many threat scenarios.',
  },
  {
    rank: 3,
    chunk_id: 2301,
    filename: DEMO_SOURCE_DOCUMENT,
    page_number: 24,
    similarity: 0.86,
    content:
      '[DEMO / SIMULATED excerpt] Useful logs record relevant events with reliable timestamps and sufficient context. Centralized collection helps correlate events across endpoints, servers, identity systems, and network devices. Monitoring should define alert thresholds, ownership, retention, access controls, and escalation procedures. Excessive noisy alerts can hide important events.',
  },
]

export function textCoversTopic(text, topic) {
  if (!text || !topic) return false
  return topic.patterns.some((pattern) => pattern.test(text))
}

export function topicsCovered(text) {
  return DEMO_TOPICS.filter((topic) => textCoversTopic(text, topic)).map(
    (topic) => topic.id,
  )
}

export function coversAllDemoTopics(text) {
  return DEMO_TOPICS.every((topic) => textCoversTopic(text, topic))
}

export function missingDemoTopics(text) {
  return DEMO_TOPICS.filter((topic) => !textCoversTopic(text, topic)).map(
    (topic) => topic.id,
  )
}

/** Full scripted demo payload for the UI. Never sent to the backend. */
export function buildCorrectionDemoPayload() {
  return {
    demo: true,
    simulated: true,
    label: 'DEMO / SIMULATED',
    source_document: DEMO_SOURCE_DOCUMENT,
    question: DEMO_QUESTION,
    correction_query: DEMO_CORRECTION_QUERY,
    status: 'ANSWERED',
    final_attempt_number: 2,
    final_answer: DEMO_ATTEMPT_2_ANSWER,
    attempts: [
      {
        attempt_number: 1,
        strategy: null,
        status: 'ANSWERED',
        answer: DEMO_ATTEMPT_1_ANSWER,
        retrieval_query: DEMO_QUESTION,
        citations: [1],
        retrieval: [DEMO_EVIDENCE[0]],
        evaluation: DEMO_ATTEMPT_1_EVALUATION,
      },
      {
        attempt_number: 2,
        strategy: 'rewrite',
        status: 'ANSWERED',
        answer: DEMO_ATTEMPT_2_ANSWER,
        retrieval_query: DEMO_CORRECTION_QUERY,
        citations: [1, 2, 3],
        retrieval: DEMO_EVIDENCE,
        evaluation: DEMO_ATTEMPT_2_EVALUATION,
      },
    ],
  }
}
