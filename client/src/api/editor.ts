import { request } from './http'
import type { Stream } from '@/types'

export interface MyCampaign {
    id: number
    name: string
    alias: string
    state: string
    created_here: boolean
}

const post = <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body })

// Own campaigns (name starts with the prefix): for the quick-pick list in the editor
export const getMyCampaigns = () => request<MyCampaign[]>('/campaigns?mine=true')

// Streams and drafts saved in our DB (no request to Keitaro): restores the page after a reload
export const getSavedStreams = (campaignId: number) =>
    request<{ campaign_id: number; streams: Stream[] }>(`/campaigns/${campaignId}/streams`)

// Fetch Streams: reads Keitaro and reconciles it with our DB
export const fetchStreams = (campaignId: number) =>
    post<{ campaign: { id: number; name: string }; streams: Stream[] }>(`/campaigns/${campaignId}/fetch`)

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