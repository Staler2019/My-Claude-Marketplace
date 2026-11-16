import type { EngineInterface, Register, RenderElement, RenderInput } from 'claude-code'

// Cells kept free on the far side of a bubble, so a long message never spans
// the whole row and the two sides stay apart.
const GUTTER = 8

// The glyph the terminal opens a tool row with, repainted in place while the
// tool runs: steady, where the engine's own blinks.
const RUNNING_DOT = '⏺'

export const register: Register = on => {
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (!e.props.isRunning) {
      return next(e)
    }

    return withRunningDot($, e, await next(e))
  })

  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    if (!e.props.isActive) {
      return next(e)
    }

    return withRunningDot($, e, await next(e))
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

// Paints a yellow dot over the first cell of the engine's row, leaving the
// rest of its drawing as it was.
const withRunningDot = ($: EngineInterface, e: RenderInput, row: RenderElement): RenderElement => {
  const { Box, Text } = $.ui.resolve(e)

  return (
    <Box>
      {row}
      <Box position="absolute" top={0} left={0}>
        <Text color="yellow">{RUNNING_DOT}</Text>
      </Box>
    </Box>
  )
}
