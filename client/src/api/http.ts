export class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
        super(message)
        this.status = status
    }
}

export async function request<T>(
    path: string,
    options: { method?: string; body?: unknown } = {},
): Promise<T> {
    const hasBody = options.body !== undefined
    const res = await fetch(`/api${path}`, {
        method: options.method ?? 'GET',
        headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
        body: hasBody ? JSON.stringify(options.body) : undefined,
    })

    const text = await res.text()
    let data: unknown = null
    try {
        data = text ? JSON.parse(text) : null
    } catch {
        /* ответ не JSON */
    }

    if (!res.ok) {
        const detail = (data as { detail?: string } | null)?.detail
        throw new ApiError(detail ?? `Error ${res.status}`, res.status)
    }
    return data as T
}