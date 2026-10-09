/**
 * CreateJobForm — submit a new generation job.
 *
 * The form is organised as a 3-step wizard (Mode → Input → Review) using
 * the ``Stepper`` primitive. Each step has a clear scope:
 *
 *   1. **Mode** — pick text / image / multiview / texture, see the
 *      model-status banner if some modes are unavailable.
 *   2. **Input** — fill the fields required by the chosen mode
 *      (prompt, image, multiview, mesh + reference).
 *   3. **Review** — pick a preset, tweak steps/guidance/seed, and
 *      submit the job.
 *
 * The wizard is *controlled*: the parent owns the current step. We
 * never advance without a valid input (the ``canSubmit`` predicate
 * drives both the "Next" gating and the final submit).
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useObjectUrl } from "./useObjectUrl";
import { buildGenerationRequest, MAX_IMAGE_BYTES, MAX_MESH_BYTES, VIEW_KEYS, type ViewKey } from "../../api/generation";
import { apiClient, errorMessage } from "../../api/client";
import { useJobEvents } from "../../context/useJobEvents";
import { useCapabilities, FALLBACK_CAPABILITIES } from "../../api/capabilities";
import { useT } from "../../i18n";

const DEFAULT_CAPABILITIES = FALLBACK_CAPABILITIES;
import {
    Stack,
    Button,
    Field,
    FieldTextarea,
    FieldFile,
    Text,
    Pill,
    Stepper,
    type StepperStep,
} from "../../design/primitives";
import { ModeChips, type ModeKey } from "./ModeChips";

const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
const MAX_IMAGE_MB = Math.round(MAX_IMAGE_BYTES / 1024 / 1024);
const MAX_MESH_MB = Math.round(MAX_MESH_BYTES / 1024 / 1024);

const VIEW_LABEL: Record<ViewKey, string> = {
    front: 'create.field.front',
    back: 'create.field.back',
    left: 'create.field.left',
    right: 'create.field.right',
};

const STEP_MODE = 0;
const STEP_INPUT = 1;
const STEP_REVIEW = 2;

export const CreateJobForm: React.FC<{ onModeChange?: (mode: ModeKey) => void }> = ({
    onModeChange,
}) => {
    const t = useT();
    const { capabilities } = useCapabilities();
    const { notifyJobSubmitted } = useJobEvents();
    const [hint, setHintInternal] = useState<ModeKey>("text");
    const setHint = (mode: ModeKey) => {
        setHintInternal(mode);
        onModeChange?.(mode);
    };
    const [text, setText] = useState("");
    const [texturePrompt, setTexturePrompt] = useState("");
    const [image, setImage] = useState<File | null>(null);
    const imagePreview = useObjectUrl(image);
    const [views, setViews] = useState<Record<ViewKey, File | null>>({
        front: null, back: null, left: null, right: null,
    });
    const viewPreviews = {
        front: useObjectUrl(views.front),
        back: useObjectUrl(views.back),
        left: useObjectUrl(views.left),
        right: useObjectUrl(views.right),
    };
    const [mesh, setMesh] = useState<File | null>(null);
    const [refImage, setRefImage] = useState<File | null>(null);
    const refPreview = useObjectUrl(refImage);

    const [steps, setSteps] = useState(50);
    const [guidance, setGuidance] = useState(5.0);
    const [seed, setSeed] = useState(1234);
    const [texture, setTexture] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [message, setMessage] = useState<
        { type: "success" | "error"; text: string } | null
    >(null);
    const [dragOver, setDragOver] = useState<ModeKey | null>(null);
    const [stepIndex, setStepIndex] = useState<number>(STEP_MODE);
    const formRef = useRef<HTMLFormElement>(null);

    // Presets from /v1/capabilities; fall back to the documented values.
    const presets = capabilities?.presets ?? DEFAULT_CAPABILITIES.presets;
    const applyPreset = (key: 'fast' | 'balanced' | 'detailed') => {
        const p = presets[key];
        if (p) {
            setSteps(p.steps);
            setGuidance(p.guidance);
        }
    };

    // Reuse parameters from the library (?reuse=<uid>).
    useEffect(() => {
        const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
        const uid = params.get('reuse');
        if (!uid) return;
        void (async () => {
            try {
                const res = await apiClient.get(`/jobs/${uid}`);
                const job = res.data;
                const req = job.request_type ?? 'unknown';
                const mode = req === 'image_to_3d' ? 'image'
                    : req === 'text_to_3d' ? 'text'
                    : req === 'multiview' ? 'multiview'
                    : req === 'texture_mesh' ? 'texture' : 'text';
                setHint(mode as ModeKey);
                setMessage({ type: 'success', text: `Reused from ${uid.slice(0, 8)}.` });
                // Clear the param so the same form doesn't re-populate later.
                const hash = window.location.hash.split('?')[0];
                window.history.replaceState({}, '', `${window.location.pathname}${window.location.search}${hash}`);
            } catch (err) {
                setMessage({ type: 'error', text: errorMessage(err) });
            }
        })();
        // setHint is stable for the lifetime of this component; intentionally
        // excluded from deps to avoid re-firing when the parent re-renders.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const setImageFile = setImage;
    const setRefImageFile = setRefImage;
    const setViewFile = (key: ViewKey, file: File | null) =>
        setViews((previous) => ({ ...previous, [key]: file }));

    function validateImage(file: File, viewLabel?: string): string | null {
        if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
            return viewLabel
                ? t('create.error.viewType', { view: viewLabel })
                : t('create.error.unsupportedType');
        }
        if (file.size > MAX_IMAGE_BYTES) {
            const msg = t('create.error.imageTooLarge', { max: MAX_IMAGE_MB });
            const viewMsg = t('create.error.viewTooLarge', { view: viewLabel ?? '', max: MAX_IMAGE_MB });
            return viewLabel ? viewMsg : msg;
        }
        return null;
    }

    const handleImagePick = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const error = validateImage(file);
        if (error) { setMessage({ type: "error", text: error }); return; }
        setImageFile(file);
        setMessage(null);
    };
    const handleViewPick =
        (key: ViewKey) => (e: React.ChangeEvent<HTMLInputElement>) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const label = t(VIEW_LABEL[key]);
            const error = validateImage(file, label);
            if (error) { setMessage({ type: "error", text: error }); return; }
            setViewFile(key, file);
            setMessage(null);
        };
    const handleMeshPick = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (!file.name.toLowerCase().endsWith(".glb")) {
            setMessage({ type: "error", text: t('create.error.meshRequired') });
            return;
        }
        if (file.size > MAX_MESH_BYTES) {
            setMessage({ type: "error", text: t('create.error.meshTooLarge', { max: MAX_MESH_MB }) });
            return;
        }
        setMesh(file);
        setMessage(null);
    };
    const handleRefPick = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const err = validateImage(file);
        if (err) { setMessage({ type: "error", text: err }); return; }
        setRefImageFile(file);
        setMessage(null);
    };

    // Generic drag-and-drop handler for the 4 input types.
    function handleDrop(mode: ModeKey, files: FileList | null) {
        if (!files || files.length === 0) return;
        const file = files[0];
        setDragOver(null);
        if (mode === 'image') {
            const err = validateImage(file);
            if (err) { setMessage({ type: 'error', text: err }); return; }
            setImageFile(file);
        } else if (mode === 'texture' && file.name.toLowerCase().endsWith('.glb')) {
            setMesh(file);
        } else if (mode === 'texture') {
            const err = validateImage(file);
            if (err) { setMessage({ type: 'error', text: err }); return; }
            setRefImageFile(file);
        } else if (mode === 'multiview') {
            const err = validateImage(file);
            if (err) { setMessage({ type: 'error', text: err }); return; }
            setViewFile('front', file);
        }
        setMessage(null);
    }

    // Whether the input step is complete enough to advance.
    const canAdvanceFromInput = useMemo(() => {
        if (hint === "text") return text.trim().length > 0;
        if (hint === "image") return image !== null;
        if (hint === "multiview") return VIEW_KEYS.every((k) => views[k] !== null);
        if (hint === "texture") return mesh !== null && (refImage !== null || texturePrompt.trim().length > 0);
        return false;
    }, [hint, text, texturePrompt, image, views, mesh, refImage]);

    // Whether the final submit can run.
    const canSubmit = useMemo(() => {
        const advancedValid =
            Number.isInteger(steps) && steps >= 1 && steps <= 100 &&
            Number.isFinite(guidance) && guidance >= 1 && guidance <= 20 &&
            Number.isSafeInteger(seed);
        return canAdvanceFromInput && advancedValid;
    }, [canAdvanceFromInput, steps, guidance, seed]);

    const goToStep = (next: number) => {
        if (next < 0) return;
        if (next > STEP_REVIEW) return;
        setStepIndex(next);
    };

    const handleNext = () => {
        if (stepIndex === STEP_MODE) {
            setStepIndex(STEP_INPUT);
            return true;
        }
        if (stepIndex === STEP_INPUT) {
            if (!canAdvanceFromInput) {
                setMessage({ type: "error", text: t('stepper.create.invalid') });
                return false;
            }
            setStepIndex(STEP_REVIEW);
            return true;
        }
        return true;
    };

    const doSubmit = async () => {
        if (!canSubmit || isSubmitting) return;
        setIsSubmitting(true);
        setMessage(null);
        try {
            const payload = await buildGenerationRequest(hint,
                { text, texturePrompt, image, views, mesh, refImage },
                { steps, guidance, seed, texture });

            const r = await apiClient.post("/generate", payload);
            setMessage({ type: "success", text: t('create.success.submittedWith', { mode: String(r.data.uid).slice(0, 8) }) });
            notifyJobSubmitted();
            if (hint === "text") setText("");
            if (hint === "image") setImage(null);
            if (hint === "multiview") setViews({ front: null, back: null, left: null, right: null });
            if (hint === "texture") { setMesh(null); setRefImage(null); setTexturePrompt(""); }
            setStepIndex(STEP_MODE);
        } catch (err) {
            setMessage({ type: "error", text: errorMessage(err) });
        } finally {
            setIsSubmitting(false);
        }
    };

    const steps_: StepperStep[] = useMemo(() => [
        {
            id: "mode",
            eyebrow: t("create.mode.text"),
            title: t("stepper.create.input.title"),
            hint: t(`create.mode.${hint}.hint`) || undefined,
        },
        {
            id: "input",
            eyebrow: t("create.advanced"),
            title: t("stepper.create.input.title"),
            hint: t("stepper.create.input.hint"),
        },
        {
            id: "review",
            eyebrow: t("nav.create"),
            title: t("stepper.create.review.title"),
            hint: t("stepper.create.review.hint"),
        },
    ], [t, hint]);

    return (
        <form id="create-job" ref={formRef} className="bg-bg" onSubmit={(e) => e.preventDefault()}>
            <Stepper
                steps={steps_}
                current={stepIndex}
                onNext={handleNext}
                onBack={() => goToStep(stepIndex - 1)}
                nextLabel={t("common.next")}
                backLabel={t("common.back")}
                submitLabel={isSubmitting ? t("create.submit.busy") : t("create.submit")}
                onSubmit={doSubmit}
                nextDisabled={stepIndex === STEP_INPUT && !canAdvanceFromInput}
                submitting={isSubmitting}
                footer={
                    <>
                        {/* Model status banner — visible only when at least one
                            backend mode is unavailable. We keep the form fully
                            interactive (the user can still pick a mode and type
                            their prompt) and surface the real error from the
                            server at submit time. */}
                        {Object.values(capabilities.modes).some((m) => m.available === false) && (
                            <div
                                role="status"
                                data-testid="model-status-banner"
                                className="rounded border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/90"
                            >
                                {t("create.banner.modelNotLoaded")}
                            </div>
                        )}

                        {/* Inline message — shown on every step so the user
                            sees validation feedback even before the submit. */}
                        {message && (
                            <Pill tone={message.type === "success" ? "success" : "danger"}>
                                {message.text}
                            </Pill>
                        )}
                    </>
                }
            >
                {/* Step 1: Mode + capability. */}
                {stepIndex === STEP_MODE && (
                    <Stack gap={4}>
                        <Text
                            voice="mono"
                            size="2xs"
                            tone="muted"
                            tracking="widest"
                            uppercase
                        >
                            {t("create.mode.text")}
                        </Text>
                        <ModeChips
                            value={hint}
                            onChange={(mode) => { setHint(mode); setMessage(null); }}
                            availability={capabilities.modes}
                        />
                    </Stack>
                )}

                {/* Step 2: Mode-specific input. */}
                {stepIndex === STEP_INPUT && (
                    <div className="space-y-4">
                        <Text
                            voice="mono"
                            size="2xs"
                            tone="muted"
                            tracking="widest"
                            uppercase
                        >
                            {t(`create.mode.${hint}`)}
                        </Text>
                        <AnimatePresence mode="wait">
                            <motion.div
                                key={hint}
                                role="tabpanel"
                                id={`mode-panel-${hint}`}
                                aria-labelledby={`mode-tab-${hint}`}
                                initial={{ opacity: 0, y: 4 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -4 }}
                                transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
                            >
                                {hint === "text" && (
                                    <FieldTextarea
                                        label={t('create.field.prompt')}
                                        hint={t('create.field.prompt.hint')}
                                        value={text}
                                        onChange={(e) => setText(e.target.value)}
                                        rows={4}
                                        autoFocus
                                    />
                                )}
                                {hint === "image" && (
                                    <Stack gap={3}>
                                        <DropZone
                                            mode="image"
                                            label={t('create.field.image')}
                                            hint={t('create.field.image.hint')}
                                            preview={imagePreview}
                                            dragOver={dragOver === 'image'}
                                            onPick={handleImagePick}
                                            onDrop={(files) => handleDrop('image', files)}
                                            onEnter={() => setDragOver('image')}
                                            onLeave={() => setDragOver(null)}
                                        />
                                    </Stack>
                                )}
                                {hint === "multiview" && (
                                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                                        {VIEW_KEYS.map((key) => (
                                            <DropZone
                                                key={key}
                                                mode="multiview"
                                                label={t(VIEW_LABEL[key])}
                                                hint=""
                                                preview={viewPreviews[key]}
                                                dragOver={dragOver === key as unknown as ModeKey}
                                                onPick={handleViewPick(key)}
                                                onDrop={(files) => handleDrop('multiview', files)}
                                                onEnter={() => setDragOver(key as unknown as ModeKey)}
                                                onLeave={() => setDragOver(null)}
                                            />
                                        ))}
                                    </div>
                                )}
                                {hint === "texture" && (
                                    <Stack gap={4}>
                                        <FieldFile
                                            label={t('create.field.mesh')}
                                            accept=".glb"
                                            onChange={handleMeshPick}
                                            filename={mesh?.name}
                                        />
                                        <FieldTextarea
                                            label={t('create.field.texturePrompt')}
                                            hint={t('create.field.texturePrompt.hint')}
                                            value={texturePrompt}
                                            onChange={(e) => setTexturePrompt(e.target.value)}
                                            rows={3}
                                        />
                                        <DropZone
                                            mode="texture"
                                            label={t('create.field.refImage')}
                                            hint={t('create.field.image.hint')}
                                            preview={refPreview}
                                            dragOver={dragOver === 'texture'}
                                            onPick={handleRefPick}
                                            onDrop={(files) => handleDrop('texture', files)}
                                            onEnter={() => setDragOver('texture')}
                                            onLeave={() => setDragOver(null)}
                                        />
                                    </Stack>
                                )}
                            </motion.div>
                        </AnimatePresence>
                    </div>
                )}

                {/* Step 3: Review and tweak. */}
                {stepIndex === STEP_REVIEW && (
                    <div className="space-y-6">
                        <Text
                            voice="mono"
                            size="2xs"
                            tone="muted"
                            tracking="widest"
                            uppercase
                        >
                            {t("create.advanced")}
                        </Text>
                        <div className="flex flex-wrap gap-2">
                            {(['fast', 'balanced', 'detailed'] as const).map((key) => {
                                const measured = presets[key]?.expected_elapsed_s;
                                const calibrated = presets[key]?.calibrated_on;
                                const hintText = measured
                                    ? `≈ ${Math.max(1, Math.round(measured))}s${calibrated ? ` @ ${calibrated}` : ''}`
                                    : null;
                                return (
                                    <Button
                                        key={key}
                                        variant="ghost"
                                        size="sm"
                                        type="button"
                                        onClick={() => applyPreset(key)}
                                        title={hintText ?? undefined}
                                    >
                                        <span className="flex flex-col items-start leading-tight">
                                            <span>{t(`create.preset.${key}`)}</span>
                                            {hintText && (
                                                <span className="text-2xs font-mono opacity-70">
                                                    {hintText}
                                                </span>
                                            )}
                                        </span>
                                    </Button>
                                );
                            })}
                        </div>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            <Field
                                label={t('create.steps')}
                                type="number"
                                min={1}
                                max={100}
                                value={steps}
                                onChange={(e) => setSteps(Number(e.target.value))}
                            />
                            <Field
                                label={t('create.guidance')}
                                type="number"
                                step={0.1}
                                min={1}
                                max={20}
                                value={guidance}
                                onChange={(e) => setGuidance(Number(e.target.value))}
                            />
                            <Field
                                label={t('create.seed')}
                                type="number"
                                value={seed}
                                onChange={(e) => setSeed(Number(e.target.value))}
                            />
                            <label className="flex items-center gap-2 mt-6">
                                <input
                                    type="checkbox"
                                    checked={texture}
                                    onChange={(e) => setTexture(e.target.checked)}
                                    className="h-4 w-4 accent-accent"
                                />
                                <span className="text-sm">{t('create.texture')}</span>
                            </label>
                        </div>
                        <Text voice="body" size="sm" tone="muted" className="leading-snug">
                            {t("stepper.create.submit.hint")}
                        </Text>
                    </div>
                )}
            </Stepper>
        </form>
    );
};

/**
 * DropZone — drop-or-click area for image/mesh uploads. Highlights while
 * a compatible file is dragged over.
 */
const DropZone: React.FC<{
    mode: ModeKey | 'multiview';
    label: string;
    hint: string;
    preview: string | null;
    dragOver: boolean;
    onPick: (e: React.ChangeEvent<HTMLInputElement>) => void;
    onDrop: (files: FileList | null) => void;
    onEnter: () => void;
    onLeave: () => void;
}> = ({ label, hint, preview, dragOver, onPick, onDrop, onEnter, onLeave }) => (
    <label
        onDragOver={(e) => { e.preventDefault(); onEnter(); }}
        onDragLeave={onLeave}
        onDrop={(e) => { e.preventDefault(); onDrop(e.dataTransfer.files); }}
        className={
            "flex flex-col gap-2 border border-dashed rounded p-3 " +
            "transition-colors duration-[120ms] " +
            (dragOver
                ? "border-accent bg-accent/10"
                : "border-border hover:border-border-strong")
        }
    >
        <Text
            voice="mono"
            size="2xs"
            tone="muted"
            tracking="widest"
            uppercase
        >
            {label}
        </Text>
        {preview ? (
            <img
                src={preview}
                alt={label}
                className="w-full max-h-32 object-contain bg-surface-1 rounded"
            />
        ) : (
            <div className="h-20 flex items-center justify-center text-fg-dim text-xs font-mono">
                ↓ drop file
            </div>
        )}
        {hint && (
            <Text voice="body" size="xs" tone="dim">
                {hint}
            </Text>
        )}
        <input
            type="file"
            accept="image/png,image/jpeg,image/webp,.glb"
            onChange={onPick}
            className="text-xs file:mr-3 file:px-2 file:py-1 file:border file:border-border file:rounded file:bg-surface-2 file:text-fg file:font-mono file:uppercase file:tracking-wider file:text-2xs"
        />
    </label>
);

export default CreateJobForm;
