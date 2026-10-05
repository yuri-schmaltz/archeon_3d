export const JobStatus = {
    QUEUED: "queued",
    PROCESSING: "processing",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled"
} as const;

export type JobStatusType = typeof JobStatus[keyof typeof JobStatus];

export type JobType = 'text_to_3d' | 'image_to_3d' | 'multiview' | 'texture_mesh';

export type MeshOpsAction = 'decimate' | 'convert';

export interface MeshOpsRequest {
    job_uid: string;
    action: MeshOpsAction;
    format?: 'glb' | 'obj' | 'ply' | 'stl';
    ratio?: number;
}

export interface BaseGenerationRequest {
    seed?: number;
    steps?: number;
    guidance?: number;
    octree_resolution?: number;
    format?: 'glb' | 'obj' | 'ply' | 'stl';
    texture?: boolean;
}

export interface TextTo3DRequest extends BaseGenerationRequest {
    type: 'text_to_3d';
    prompt: string;
}

export interface ImageTo3DRequest extends BaseGenerationRequest {
    type: 'image_to_3d';
    image: string; // Base64
    remove_background?: boolean;
}

export interface MultiviewRequest extends BaseGenerationRequest {
    type: 'multiview';
    front: string; // Base64
    back: string;
    left: string;
    right: string;
}

export type JobRequest = TextTo3DRequest | ImageTo3DRequest | MultiviewRequest;

export interface JobResponse {
    uid: string;
    status: JobStatusType;
    created_at: string;
    updated_at?: string;
    completed_at?: string;
    error?: string;
    file_path?: string;
    request_type?: JobType;
    stage?: string | null;
    stage_progress?: number | null;
}

/**
 * Compact event record emitted by the SSE feeds. The frontend builds
 * a synthetic stream of these from the jobs list (one event per
 * (uid, status) transition) so chrome components (header, ticker)
 * can render a single uniform event log.
 */
export interface JobEvent {
    uid: string;
    status: JobStatusType;
    /** ISO-8601 timestamp; falls back to created_at. */
    at: string;
    request_type?: JobType;
}

export interface SystemMetrics {
    /** Seconds since the backend process started. */
    uptime_seconds: number;
    /** Process-level metrics. The backend may also return the same
        fields flat (legacy shape); both are accepted. */
    process?: {
        pid: number;
        rss_mb: number;
        vms_mb: number;
        threads: number;
        cpu_percent: number;
    };
    /** Legacy flat fields (some endpoints return these directly). */
    cpu_percent?: number;
    ram_bytes?: number;
    vms_bytes?: number;
    /** GPU utilisation percentage (0–100), if a GPU is present. */
    gpu_percent?: number;
    /** GPU memory currently allocated, in bytes. */
    gpu_mem_used?: number;
    /** GPU total memory, in bytes. */
    gpu_mem_total?: number;
    /** Number of jobs currently in memory. */
    jobs_in_memory?: number;
    /** Number of jobs persisted in the SQLite store. */
    jobs_in_store?: number;
    /** Whether the SQLite persistence layer is enabled. */
    persistence_enabled?: boolean;
    /** GPU handle, if available. */
    gpu?: {
        name: string;
        memory_allocated_mb: number;
        memory_reserved_mb: number;
        memory_total_mb: number;
    };
}
