import {Component, type ErrorInfo, type ReactNode} from 'react';
import {AlertTriangle} from 'lucide-react';
import {Button} from './Button';

interface Props {
    children: ReactNode;
    /** Optional custom fallback. Receives a reset callback to retry rendering. */
    fallback?: (reset: () => void) => ReactNode;
}

interface State {
    error: Error | null;
}

/**
 * Catches render-time errors in the routed content so a single broken screen
 * shows a friendly retry panel instead of a blank white page.
 */
export class ErrorBoundary extends Component<Props, State> {
    state: State = {error: null};

    static getDerivedStateFromError(error: Error): State {
        return {error};
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        // eslint-disable-next-line no-console
        console.error('Unhandled UI error:', error, info.componentStack);
    }

    reset = () => this.setState({error: null});

    render() {
        if (!this.state.error) return this.props.children;
        if (this.props.fallback) return this.props.fallback(this.reset);

        return (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
                <div className="mb-4 rounded-full bg-danger-50 p-4">
                    <AlertTriangle className="h-8 w-8 text-danger"/>
                </div>
                <h3 className="mb-1 text-base font-semibold text-gray-900">Something went wrong</h3>
                <p className="mb-4 max-w-sm text-sm text-gray-500">
                    This screen ran into an unexpected error. You can try again — if it keeps
                    happening, refresh the page or contact support.
                </p>
                <Button variant="outline" onClick={this.reset}>Try again</Button>
            </div>
        );
    }
}
