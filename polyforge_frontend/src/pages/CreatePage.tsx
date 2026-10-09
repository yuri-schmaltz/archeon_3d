import React, { useState } from 'react';
import { useT } from '../i18n';
import { CreateJobForm } from '../components/jobs/CreateJobForm';
import { CapabilityStrip } from '../components/jobs/CapabilityStrip';
import { Text } from '../design/primitives';
import type { ModeKey } from '../components/jobs/ModeChips';

export const CreatePage: React.FC = () => {
    const t = useT();
    const [mode, setMode] = useState<ModeKey>('text');
    return (
        <section className="space-y-6">
            <header className="space-y-3">
                <Text
                    as="h1"
                    voice="display"
                    size="xl"
                    tracking="tight"
                >
                    {t('create.heading')}
                </Text>
                <Text voice="body" size="sm" tone="muted" className="leading-snug">
                    {t('create.heading.hint')}
                </Text>
                <CapabilityStrip mode={mode} dense />
            </header>
            <CreateJobForm onModeChange={setMode} />
        </section>
    );
};
