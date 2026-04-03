const SAMPLE_MARKDOWN = `Here is a **demo** reply (no backend). Your message was received.

- Bullet one
- Bullet two

Example code:

\`\`\`python
def hello(name: str) -> str:
    return f"Hello, {name}!"
\`\`\`

When the real agent is wired in, this area will show the model answer and the trace below will reflect real tool calls.`

export function buildMockTrace(userText: string) {
  return {
    mode: 'demo',
    steps: [
      {
        type: 'planner',
        summary: 'Parsed user intent and selected tools (mock)',
        ts: new Date().toISOString(),
      },
      {
        type: 'tool_call',
        tool: 'calculator',
        input: { expression: '2 + 2' },
        output: 4,
        latency_ms: 12,
      },
      {
        type: 'tool_call',
        tool: 'weather',
        input: { city: 'Demo City' },
        output: { temp_c: 21, conditions: 'partly cloudy (mock)' },
        latency_ms: 180,
      },
    ],
    echo_preview:
      userText.length > 120 ? `${userText.slice(0, 120)}…` : userText,
  }
}

export function mockAssistantReply(userText: string): {
  body: string
  trace: ReturnType<typeof buildMockTrace>
} {
  const quoted =
    userText.trim() === ''
      ? '_You sent an empty message._'
      : `You asked:\n\n> ${userText.trim().replace(/\n/g, '\n> ')}\n\n`
  return {
    body: `${quoted}\n\n${SAMPLE_MARKDOWN}`,
    trace: buildMockTrace(userText),
  }
}
