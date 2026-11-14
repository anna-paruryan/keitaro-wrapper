export interface Option { id: number; name: string }
export interface OfferShort { id: number; name: string; state: string }

export type Meta = {
    prefix: string
    google_url: string
    domains: Option[]
    groups: Option[]
    sources: Option[]
    notes: Record<string, string>
    defaults: {
        domain_id: number | null
        group_id: number | null
        traffic_source_id: number | null
    }
}

export interface CreateCampaignBody {
    name: string
    geo: string
    offer_id: number
    domain_id?: number
    group_id?: number
    traffic_source_id?: number
}

export type CreateCampaignResult = {
    campaign: { id: number; name: string; alias: string; tracker_url: string | null }
    streams: { id: number | null; position: number; title: string }[]
    geo: string[]
    offer: OfferShort
    settings: { domain: string | null; group: string | null; source: string | null }
    notes: Record<string, string>
    warning: string | null
}

export type OfferStatus = 'active' | 'new' | 'removed'
export interface StreamOffer {
    offer_id: number
    name: string
    share: number
    pinned: boolean
    status: OfferStatus   // active = белая, new = жёлтая, removed = серая
    dirty: boolean
}
export interface Offer {
    offer_id: number
    name: string
    share: number
    pinned: boolean
    status: OfferStatus
}

export interface Stream {
    id: number            // ID потока в Keitaro
    campaign_id: number
    name: string
    position: number
    has_offers: boolean   // false = поток-редирект: рисуем только заголовок
    dirty: boolean        // true = поток жёлтый, показываем Push и Cancel
    offers: StreamOffer[]
}