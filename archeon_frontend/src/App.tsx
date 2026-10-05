import { Suspense, lazy } from 'react';
import { motion } from 'framer-motion';
import { AppShell } from './components/AppShell';
import { CreatePage } from './pages/CreatePage';
import { JobDetailDrawer } from './components/library/JobDetailDrawer';
import { useDetailUid } from './hooks/useDetailUid';
import { RouteMatch } from './router/RouteMatch';
import { Text } from './design/primitives';

// Code-split the secondary pages so the initial bundle stays small.
// CreatePage stays eager: it is the main interactive surface.
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })));
const SystemPage = lazy(() => import('./pages/SystemPage').then((m) => ({ default: m.SystemPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));

const EASE = [0.16, 1, 0.3, 1] as const;
const container = {
    hidden: { opacity: 0 },
    show: {
        opacity: 1,
        transition: { staggerChildren: 0.06, delayChildren: 0.1 },
    },
};
const item = {
    hidden: { opacity: 0, y: 8 },
    show: {
        opacity: 1,
        y: 0,
        transition: { duration: 0.5, ease: EASE },
    },
};

const PageFallback: React.FC = () => (
    <div className="py-12 text-center text-fg-muted">
        <Text voice="mono" size="xs" uppercase>loading…</Text>
    </div>
);

function App() {
    const [selectedUid, closeDetail] = useDetailUid();
    return (
        <AppShell>
            <motion.div initial="hidden" animate="show" variants={container}>
                <motion.div variants={item}>
                    <RouteMatch id="create">
                        <CreatePage />
                    </RouteMatch>
                    <RouteMatch id="library">
                        <Suspense fallback={<PageFallback />}>
                            <LibraryPage />
                        </Suspense>
                    </RouteMatch>
                    <RouteMatch id="system">
                        <Suspense fallback={<PageFallback />}>
                            <SystemPage />
                        </Suspense>
                    </RouteMatch>
                    <RouteMatch id="settings">
                        <Suspense fallback={<PageFallback />}>
                            <SettingsPage />
                        </Suspense>
                    </RouteMatch>
                </motion.div>
            </motion.div>
            <JobDetailDrawer uid={selectedUid} onClose={closeDetail} />
        </AppShell>
    );
}

export default App;
