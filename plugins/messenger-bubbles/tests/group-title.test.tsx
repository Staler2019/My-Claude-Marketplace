import { expect, mock, test } from 'claude-code/testing'

// `find` matches on type, key and text alone, so props are checked here.
const withProps = async (
  ui: { findAll: (q: { type: string }) => Promise<{ props: Record<string, unknown>; text: string }[]> },
  type: string,
  props: Record<string, unknown>,
  text?: string,
) =>
  (await ui.findAll({ type })).find(
    el => Object.entries(props).every(([k, v]) => el.props[k] === v) && (text === undefined || el.text === text),
  )

const CALL = {
  tool_use_id: 't1',
  tool: 'Bash',
  input: { command: 'python3 count.py', description: 'Counting to ten' },
  isRunning: true,
  isErrored: false,
  isInterrupted: false,
}

const GROUP = {
  plugin: 'messenger-bubbles',
  component: 'ToolGroup',
  surface: 'terminal',
  props: { calls: [CALL], isActive: true, isExpanded: false },
} as const

test('a live group titles its running call in yellow, counting seconds', async ($, on) => {
  const clock = mock.clock(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount(GROUP)
  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺ Counting to ten · 0s')).toBeTruthy()

  await clock.advance(5000)
  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺ Counting to ten · 5s')).toBeTruthy()

  await clock.advance(60000)
  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺ Counting to ten · 1m 5s')).toBeTruthy()
  await ui.unmount()
})

test('a call with no description is titled by its input', async ($, on) => {
  mock.clock(on)
  const ui = await $.ui.mount({
    ...GROUP,
    props: { ...GROUP.props, calls: [{ ...CALL, tool_use_id: 't2', input: { command: 'ls -la' } }] },
  })

  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺ Bash(ls -la) · 0s')).toBeTruthy()
  await ui.unmount()
})
