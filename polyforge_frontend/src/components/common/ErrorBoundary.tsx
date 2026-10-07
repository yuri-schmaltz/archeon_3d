import React from 'react';

interface ErrorBoundaryProps {
    children: React.ReactNode;
    fallback?: React.ReactNode;
}

interface ErrorBoundaryState {
    hasError: boolean;
    error: Error | null;
}

/**
 * Catches render-time exceptions in any descendant component and renders a
 * recoverable fallback. Without this, a malformed API response (e.g. backend
 * returns a field the frontend types don't include) will white-screen the
 * entire app because React 19 has no built-in error boundary.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
    constructor(props: ErrorBoundaryProps) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error: Error): ErrorBoundaryState {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: React.ErrorInfo): void {
        console.error('PolyForge UI crashed:', error, info);
    }

    private handleReload = () => {
        window.location.reload();
    };

    render() {
        if (this.state.hasError) {
            if (this.props.fallback) {
                return this.props.fallback;
            }
            return (
                <div
                    role="alert"
                    className="min-h-screen flex items-center justify-center bg-bg text-gray-200 p-8"
                >
                    <div className="max-w-md text-center space-y-4">
                        <h1 className="text-2xl font-bold text-red-400">Something went wrong</h1>
                        <p className="text-sm text-gray-400">
                            {this.state.error?.message ?? 'An unexpected error occurred.'}
                        </p>
                        <button
                            onClick={this.handleReload}
                            className="bg-accent hover:opacity-90 text-white px-4 py-2 rounded"
                        >
                            Reload
                        </button>
                    </div>
                </div>
            );
        }
        return this.props.children;
    }
}
