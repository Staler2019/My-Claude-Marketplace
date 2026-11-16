// The clock's time at the last tick, which redraws a live group's title.
export type Now = number

declare module 'claude-code' {
  interface PluginState {
    'messenger-bubbles': { now: Now }
  }
}
