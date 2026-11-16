import { expect, test } from 'claude-code/testing'

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

  const row = await ui.find({ type: 'Box', props: { justifyContent: 'flex-end' } })
  expect(row).toBeTruthy()
  const bubble = await ui.find({ type: 'Box', props: { borderStyle: 'round' } })
  expect(bubble).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /hello there/ }))?.text).toBe('hello there')
  await ui.unmount()
})

test('a reply is a bubble on the left, drawn as markdown', async ($, on) => {
  const ui = await $.ui.mount(ASSISTANT)

  const row = await ui.find({ type: 'Box', props: { justifyContent: 'flex-start' } })
  expect(row).toBeTruthy()
  const bubble = await ui.find({ type: 'Box', props: { borderStyle: 'round' } })
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
  expect(await ui.find({ type: 'Box', props: { borderStyle: 'round' } })).toBeFalsy()
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

  expect(await ui.find({ type: 'Box', props: { justifyContent: 'flex-start' } })).toBeTruthy()
  expect(await ui.find({ type: 'Box', props: { borderStyle: 'round' } })).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /engine summary/ }))?.text).toBe('engine summary')
  await ui.unmount()
})
