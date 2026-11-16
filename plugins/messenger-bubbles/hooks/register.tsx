import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderElement, RenderInput } from 'claude-code'

// Cells kept free on the far side of a bubble, so a long message never spans
// the whole row and the two sides stay apart.
const GUTTER = 8

// The glyph the terminal opens a tool row with, repainted in place while the
// tool runs: steady, where the engine's own blinks.
const RUNNING_DOT = '⏺'

const now = atom({ plugin: 'messenger-bubbles', key: 'now' } as const, 0)

export const register: Register = on => {
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (!e.props.isRunning) {
      return next(e)
    }

    // ctrl+o shows the engine's full row; only its dot turns yellow there.
    if (e.props.isExpanded) {
      return withRunningDot($, e, await next(e))
    }

    const { Box, Text } = $.ui.resolve(e)

    return (
      <Box marginTop={DOT_ROW}>
        <Text color="yellow" wrap="truncate-end">
          {`${RUNNING_DOT} ${e.props.tool}(${argumentOf(e.props.input)})`}
        </Text>
      </Box>
    )
  })

  // When the mod first saw each running call of a live group, by call; the
  // engine keeps its own elapsed time to itself, so the title counts from here.
  const startedAt = new Map<string, number>()

  on('session.start', async ($, e, next) => {
    // Ticks only while a live group is counting, so a quiet session redraws nothing.
    $.clock.every(1000, async () => {
      if (startedAt.size > 0) {
        const time = await $.clock.now()
        await update($, now, () => time)
      }
    })

    return next(e)
  })

  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    if (!e.props.isActive) {
      startedAt.clear()

      return next(e)
    }

    const call = e.props.calls.findLast(c => c.isRunning)

    if (e.props.isExpanded || call === undefined) {
      return withRunningDot($, e, await next(e))
    }

    const id = call.tool_use_id ?? `${call.tool}:${JSON.stringify(call.input)}`
    const time = Math.max(await read($, now), await $.clock.now())
    const start = startedAt.get(id) ?? time
    startedAt.set(id, start)

    const { Box, Text } = $.ui.resolve(e)
    const description = descriptionOf(call.input)
    const title = description ?? `${call.tool}(${argumentOf(call.input)})`

    return (
      <Box marginTop={DOT_ROW}>
        <Text color="yellow" wrap="truncate-end">
          {`${RUNNING_DOT} ${title} · ${elapsed(time - start)}`}
        </Text>
      </Box>
    )
  })

  on('ui.render', { component: 'UserMessage' }, ($, e, next) => {
    // Only the person's own prompts become bubbles; notifications and messages
    // from other agents keep the engine's row, and ctrl+o still shows it whole.
    if (e.props.origin.kind !== 'composer' || e.props.isExpanded) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="row" justifyContent="flex-end" marginTop={1}>
        <Box borderStyle="round" borderColor="suggestion" paddingX={1} flexShrink={1} marginLeft={GUTTER}>
          <Text>{e.props.text}</Text>
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const { Box, Markdown } = $.ui.resolve(e)

    // A summary row carries a mark only the engine's drawing keeps, so the
    // bubble wraps that drawing instead of redrawing the text.
    const body = e.props.isSummary ? await next(e) : <Markdown text={e.props.text} />

    return (
      <Box flexDirection="row" justifyContent="flex-start" marginTop={1}>
        <Box borderStyle="round" borderColor="claude" paddingX={1} flexShrink={1} marginRight={GUTTER}>
          {body}
        </Box>
      </Box>
    )
  })
}

// The engine's tool row opens with one blank line above the dot.
const DOT_ROW = 1

// Paints a yellow dot over the first cell of the engine's row, leaving the
// rest of its drawing as it was.
const withRunningDot = ($: EngineInterface, e: RenderInput, row: RenderElement): RenderElement => {
  const { Box, Text } = $.ui.resolve(e)

  return (
    <Box>
      {row}
      <Box position="absolute" top={DOT_ROW} left={0}>
        <Text color="yellow">{RUNNING_DOT}</Text>
      </Box>
    </Box>
  )
}

// The input field a tool's title shows, by the field each built-in names its
// target with; any other tool shows its first string field.
const TITLE_FIELDS = ['command', 'file_path', 'notebook_path', 'pattern', 'url', 'query', 'description']

const argumentOf = (input: unknown): string => {
  if (typeof input !== 'object' || input === null) {
    return ''
  }

  const fields = input as Record<string, unknown>
  const named = TITLE_FIELDS.map(field => fields[field]).find(value => typeof value === 'string')
  const value = named ?? Object.values(fields).find(value => typeof value === 'string')

  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : ''
}

// What a call says it is doing, as the model described it (Bash's `description`).
const descriptionOf = (input: unknown): string | undefined => {
  if (typeof input !== 'object' || input === null) {
    return undefined
  }

  const description = (input as Record<string, unknown>).description

  return typeof description === 'string' && description.trim() !== ''
    ? description.replace(/\s+/g, ' ').trim()
    : undefined
}

// Elapsed time as the engine writes it: `5s`, then `1m 5s`.
const elapsed = (ms: number): string => {
  const seconds = Math.floor(ms / 1000)

  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}
