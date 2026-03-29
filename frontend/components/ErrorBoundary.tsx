"use client";

import React from "react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[ErrorBoundary] Caught error:", error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="border border-danger/40 bg-danger/5 rounded p-4 space-y-3 font-mono">
          <div className="flex items-center gap-2">
            <span className="text-danger text-xs font-bold tracking-widest">
              ERROR
            </span>
            <span className="text-muted text-[10px]">COMPONENT FAILURE</span>
          </div>
          <div className="text-danger text-xs break-all">
            {this.state.error?.message ?? "An unexpected error occurred"}
          </div>
          <button
            onClick={this.handleRetry}
            className="font-mono text-xs border border-border text-muted hover:text-white hover:border-accent px-3 py-1.5 rounded transition-colors min-h-[44px]"
          >
            RETRY
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
