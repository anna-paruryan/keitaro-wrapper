import { request } from './http'
import type { Stream } from '@/types'

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body })

export const fetchStreams = (campaignId: number) =>
    post<{ streams: Stream[] }>(`/campaigns/${campaignId}/fetch`)

export const addOffer = (streamId: number, offerId: number) =>
    post<Stream>(`/streams/${streamId}/offers`, { offer_id: offerId })

export const removeOffer = (streamId: number, offerId: number) =>
    post<Stream>(`/streams/${streamId}/offers/${offerId}/remove`)

export const restoreOffer = (streamId: number, offerId: number) =>
    post<Stream>(`/streams/${streamId}/offers/${offerId}/restore`)

export const pinOffer = (streamId: number, offerId: number, pinned: boolean) =>
    post<Stream>(`/streams/${streamId}/offers/${offerId}/pin`, { pinned })

export const pushStream = (streamId: number) => post<Stream>(`/streams/${streamId}/push`)

export const cancelStream = (streamId: number) => post<Stream>(`/streams/${streamId}/cancel`)