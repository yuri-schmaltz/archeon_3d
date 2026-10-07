import React, { useSyncExternalStore } from "react";
import { PageHeader } from "./PageHeader";
import { StatusTicker } from "./StatusTicker";
import { LeftRail } from "./LeftRail";
import { BottomTabs } from "./BottomTabs";
import { useEnsureDefaultRoute } from "../router";

const desktopQuery = "(min-width: 1024px)";
const subscribeLayout = (callback: () => void) => {
    if (typeof window === 'undefined') return () => undefined;
    const media = window.matchMedia(desktopQuery);
    media.addEventListener("change", callback);
    return () => media.removeEventListener("change", callback);
};

const getDesktop = () =>
    typeof window === 'undefined' ? false : window.matchMedia(desktopQuery).matches;

const getDesktopSSR = () => false;

export const AppShell: React.FC<{ children: React.ReactNode }> = ({
    children,
}) => {
    useEnsureDefaultRoute();
    const desktop = useSyncExternalStore(subscribeLayout, getDesktop, getDesktopSSR);
    return (
        <div className="h-dvh flex flex-col bg-bg text-fg">
            <PageHeader />
            <div className="flex-1 min-h-0 flex overflow-hidden">
                {desktop && <LeftRail />}
                <main className="flex-1 min-w-0 overflow-y-auto">
                    <div className="max-w-5xl mx-auto px-5 py-6 sm:px-8 sm:py-8 lg:px-10 lg:py-10">
                        {children}
                    </div>
                </main>
            </div>
            <StatusTicker />
            {!desktop && <BottomTabs />}
        </div>
    );
};

export default AppShell;
