import React from 'react';
import { useT } from '../i18n';
import { CreateJobForm } from '../components/jobs/CreateJobForm';
import { Text } from '../design/primitives';

export const CreatePage: React.FC = () => {
    const t = useT();
    return (
        <section className="space-y-6">
            <header className="space-y-1">
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
            </header>
            <CreateJobForm />
        </section>
    );
};
