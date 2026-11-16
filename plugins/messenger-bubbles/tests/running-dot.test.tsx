import { expect, test } from 'claude-code/testing'
import type { TestBody } from 'claude-code/testing'

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

const TOOL = {
  plugin: 'messenger-bubbles',
  component: 'ToolUse',
  surface: 'terminal',
  props: {
    tool_use_id: 't1',
    tool: 'Bash',
    input: { command: 'ls' },
    isRunning: true,
    isErrored: false,
    isInterrupted: false,
  },
} as const

const GROUP = {
  plugin: 'messenger-bubbles',
  component: 'ToolGroup',
  surface: 'terminal',
  props: { calls: [], isActive: true, isExpanded: false },
} as const

const engine = (on: Parameters<TestBody>[1]) =>
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine row</Text>
  })

test('a running tool paints a yellow dot over the engine row', async ($, on) => {
  engine(on)
  const ui = await $.ui.mount(TOOL)

  expect(await withProps(ui, 'Box', { position: 'absolute', top: 0, left: 0 })).toBeTruthy()
  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺')).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /engine row/ }))?.text).toBe('engine row')
  await ui.unmount()
})

test('a finished tool keeps the engine dot', async ($, on) => {
  engine(on)
  const ui = await $.ui.mount({ ...TOOL, props: { ...TOOL.props, isRunning: false } })

  expect(await withProps(ui, 'Text', { color: 'yellow' })).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /engine row/ }))?.text).toBe('engine row')
  await ui.unmount()
})

test('a live tool group paints a yellow dot too', async ($, on) => {
  engine(on)
  const ui = await $.ui.mount(GROUP)

  expect(await withProps(ui, 'Text', { color: 'yellow' }, '⏺')).toBeTruthy()
  await ui.unmount()
})

test('a settled tool group keeps the engine dot', async ($, on) => {
  engine(on)
  const ui = await $.ui.mount({ ...GROUP, props: { ...GROUP.props, isActive: false } })

  expect(await withProps(ui, 'Text', { color: 'yellow' })).toBeFalsy()
  await ui.unmount()
})
