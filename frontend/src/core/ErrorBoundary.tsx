import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("SightGuide UI error:", error, info);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <main className="app-shell" aria-label="SightGuide error">
          <header className="topbar">
            <button className="brand-mark" type="button" onClick={() => this.setState({ error: null })} aria-label="Retry">◉</button>
            <h1>SightGuide AI</h1>
          </header>
          <section className="feature-screen" role="alert">
            <span className="eyebrow">Something went wrong</span>
            <h2>That screen could not be displayed.</h2>
            <p>{this.state.error.message || "An unexpected error occurred."}</p>
            <button className="primary-action" type="button" onClick={() => this.setState({ error: null })}>
              Try again
            </button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
