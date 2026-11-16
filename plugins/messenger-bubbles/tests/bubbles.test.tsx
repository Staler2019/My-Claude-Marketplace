import { expect, test } from 'claude-code/testing'

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

const USER = {
  plugin: 'messenger-bubbles',
  component: 'UserMessage',
  surface: 'terminal',
  props: { text: 'hello there', origin: { kind: 'composer' }, isExpanded: false },
} as const

const ASSISTANT = {
  plugin: 'messenger-bubbles',
  component: 'AssistantMessage',
  surface: 'terminal',
  props: { text: 'hi **you**', isFirstOfReply: true },
} as const

test('my prompt is a bubble pushed to the right', async ($, on) => {
  const ui = await $.ui.mount(USER)

  const row = await withProps(ui, 'Box', { justifyContent: 'flex-end' })
  expect(row).toBeTruthy()
  const bubble = await withProps(ui, 'Box', { borderStyle: 'round' })
  expect(bubble).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /hello there/ }))?.text).toBe('hello there')
  await ui.unmount()
})

test('a reply is a bubble on the left, drawn as markdown', async ($, on) => {
  const ui = await $.ui.mount(ASSISTANT)

  const row = await withProps(ui, 'Box', { justifyContent: 'flex-start' })
  expect(row).toBeTruthy()
  const bubble = await withProps(ui, 'Box', { borderStyle: 'round' })
  expect(bubble).toBeTruthy()
  expect(await ui.find({ type: 'Markdown' })).toBeTruthy()
  await ui.unmount()
})

test('a task notification keeps the engine row', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

  const ui = await $.ui.mount({
    ...USER,
    props: { ...USER.props, origin: { kind: 'task-notification' } },
  })

  expect((await ui.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  expect(await withProps(ui, 'Box', { borderStyle: 'round' })).toBeFalsy()
  await ui.unmount()
})

test('a summary row is wrapped in a left bubble, keeping the engine drawing', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine summary</Text>
  })

  const ui = await $.ui.mount({
    ...ASSISTANT,
    props: { ...ASSISTANT.props, isSummary: true },
  })

  expect(await withProps(ui, 'Box', { justifyContent: 'flex-start' })).toBeTruthy()
  expect(await withProps(ui, 'Box', { borderStyle: 'round' })).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /engine summary/ }))?.text).toBe('engine summary')
  await ui.unmount()
})
