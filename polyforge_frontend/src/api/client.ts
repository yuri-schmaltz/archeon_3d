import axios from 'axios';

const configuredUrl = import.meta.env.VITE_API_URL;
export const BASE_URL = (configuredUrl !== undefined
    ? configuredUrl
    : import.meta.env.DEV ? 'http://localhost:8081' : '').replace(/\/+$/, '');
export const API_URL = `${BASE_URL}/v1`;
export const AUTH_REQUIRED_EVENT = 'polyforge:auth-required';
let apiKey = '';

export function setApiKey(value: string): void {
    apiKey = value.trim();
}

export function authHeaders(): Record<string, string> {
    return apiKey ? { 'X-API-Key': apiKey } : {};
}

export function requestAuthentication(): void {
    window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
}

export const apiClient = axios.create({ baseURL: API_URL, timeout: 60_000 });
apiClient.interceptors.request.use((config) => {
    for (const [name, value] of Object.entries(authHeaders())) config.headers.set(name, value);
    return config;
});
apiClient.interceptors.response.use((response) => response, (error) => {
    if (axios.isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)) {
        requestAuthentication();
    }
    return Promise.reject(error);
});

export function errorMessage(error: unknown): string {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail;
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return detail.map((item) => item.msg).join('; ');
    }
    return error instanceof Error ? error.message : 'The request failed. Please try again.';
}
