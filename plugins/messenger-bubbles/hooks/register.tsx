import type { Register } from 'claude-code'

// Cells kept free on the far side of a bubble, so a long message never spans
// the whole row and the two sides stay apart.
const GUTTER = 8

export const register: Register = on => {
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

  on('ui.render', { component: 'AssistantMessage' }, ($, e, next) => {
    // A summary row carries a mark only the engine's drawing keeps.
    if (e.props.isSummary) {
      return next(e)
    }

    const { Box, Markdown } = $.ui.resolve(e)

    return (
      <Box flexDirection="row" justifyContent="flex-start" marginTop={1}>
        <Box borderStyle="round" borderColor="claude" paddingX={1} flexShrink={1} marginRight={GUTTER}>
          <Markdown text={e.props.text} />
        </Box>
      </Box>
    )
  })
}
