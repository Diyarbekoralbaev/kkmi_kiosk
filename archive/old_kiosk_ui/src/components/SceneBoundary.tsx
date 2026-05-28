import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  err: Error | null
}

export class SceneBoundary extends Component<Props, State> {
  state: State = { err: null }

  static getDerivedStateFromError(err: Error): State {
    return { err }
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('[SceneBoundary]', err, info.componentStack)
  }

  render() {
    if (this.state.err) {
      return (
        <div className="w-full h-full flex items-center justify-center font-mono text-xs text-red-400 p-4 text-center">
          scene crashed: {this.state.err.message}
        </div>
      )
    }
    return this.props.children
  }
}
