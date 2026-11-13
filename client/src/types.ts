export interface Option { id: number; name: string }
export interface OfferShort { id: number; name: string; state: string }

export interface Meta {
    prefix: string
    google_url: string
    domains: Option[]
    groups: Option[]
    sources: Option[]
    defaults: { domain_id: number | null; group_id: number | null; traffic_source_id: number | null }
}

export interface CreateCampaignBody {
    name: string
    geo: string
    offer_id: number
    domain_id?: number
    group_id?: number
    traffic_source_id?: number
}

export interface CreateCampaignResult {
    campaign: { id: number; name: string; alias: string; tracker_url: string | null }
    streams: { id: number | null; position: number; title: string }[]
    geo: string[]
    offer: OfferShort
    settings: { domain: string; group: string; source: string }
    warning: string | null
}

export type OfferStatus = 'active' | 'new' | 'removed'

export interface Offer {
    offer_id: number
    name: string
    share: number
    pinned: boolean
    status: OfferStatus
}

export interface Stream {
    id: number
    name: string
    position: number
    is_dirty: boolean
    offers: Offer[]
}