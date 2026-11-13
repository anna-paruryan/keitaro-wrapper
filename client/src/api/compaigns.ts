import { request } from './http'
import type { CreateCampaignBody, CreateCampaignResult, Meta, OfferShort } from '@/types'

export const getMeta = () => request<Meta>('/meta')

export const searchOffers = (q: string) =>
    request<OfferShort[]>(`/offers?q=${encodeURIComponent(q)}&limit=15`)

export const createCampaign = (body: CreateCampaignBody) =>
    request<CreateCampaignResult>('/campaigns', { method: 'POST', body })