import axios from 'axios';
import { apiClient, authHeaders } from './client';

export interface SignedUrlResponse {
    url: string;
    expires_at: number;
    ttl_seconds: number;
}

/**
 * Mint a short-lived signed URL for a job's mesh output. Falls back
 * to ``null`` when the backend doesn't have URL signing configured
 * (returns 503); callers should use the legacy /files/<name> path
 * with the API key header in that case.
 */
export async function signedDownloadUrl(uid: string): Promise<string | null> {
    try {
        const response = await apiClient.get<SignedUrlResponse>(
            `/jobs/${encodeURIComponent(uid)}/download-url`,
            { headers: authHeaders() },
        );
        return response.data.url;
    } catch (err) {
        // 503 = signing not configured; older setups use the API key
        // header directly. Other errors bubble up.
        if (axios.isAxiosError(err) && err.response?.status === 503) {
            return null;
        }
        throw err;
    }
}