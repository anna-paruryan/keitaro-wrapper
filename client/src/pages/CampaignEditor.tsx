import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchStreams, getMyCampaigns, getSavedStreams } from '@/api/editor'
import StreamCard from '@/components/StreamCard'
import type { Stream } from '@/types'

const STORAGE_KEY = 'editor.campaignId'

type SavedStreams = { campaign_id: number; streams: Stream[] }

// The browser only remembers WHICH campaign was open. The drafts themselves live in our DB.
function loadLastId(): number | null {
    try {
        const id = Number(localStorage.getItem(STORAGE_KEY))
        return Number.isInteger(id) && id > 0 ? id : null
    } catch {
        return null
    }
}

function saveLastId(id: number) {
    try {
        localStorage.setItem(STORAGE_KEY, String(id))
    } catch {
        /* storage may be unavailable: not critical */
    }
}

export default function CampaignEditor() {
    const queryClient = useQueryClient()
    const [activeId, setActiveId] = useState<number | null>(loadLastId) // campaign shown on the page
    const [input, setInput] = useState(() => (activeId ? String(activeId) : ''))
    const [campaignName, setCampaignName] = useState('')

    // Saved state from our DB (no request to Keitaro): this is what restores the page after a reload
    const saved = useQuery({
        queryKey: ['saved-streams', activeId],
        queryFn: () => getSavedStreams(activeId as number),
        enabled: activeId !== null,
        staleTime: Infinity, // the cache is updated by Fetch and by the buttons, no need to refetch
    })

    const myCampaigns = useQuery({ queryKey: ['my-campaigns'], queryFn: getMyCampaigns })

    const fetchMutation = useMutation({
        mutationFn: (id: number) => fetchStreams(id),
        onSuccess: (data, id) => {
            queryClient.setQueryData(['saved-streams', id], { campaign_id: id, streams: data.streams })
            setActiveId(id)
            setCampaignName(data.campaign.name)
            saveLastId(id)
        },
        onError: () => {
            // do not leave the previous campaign on screen next to a new ID
            setActiveId(null)
            setCampaignName('')
        },
    })

    // After F5 the name is not in memory any more: take it from the "My campaigns" list
    const title = campaignName || myCampaigns.data?.find((c) => c.id === activeId)?.name

    const id = Number(input)
    const canFetch = Number.isInteger(id) && id > 0 && !fetchMutation.isPending
    const streams = saved.data?.streams ?? []

    // A button returned the updated stream: put it in place of the old one in the cache
    function replaceStream(updated: Stream) {
        queryClient.setQueryData<SavedStreams>(['saved-streams', activeId], (old) =>
            old ? { ...old, streams: old.streams.map((s) => (s.id === updated.id ? updated : s)) } : old,
        )
    }

    function pick(campaignId: number) {
        setInput(String(campaignId))
        fetchMutation.mutate(campaignId)
    }

    return (
        <>
            <h1 className="title">Editor</h1>
            <p className="hint">Pick one of your campaigns or enter its ID, then fetch its streams from Keitaro.</p>

            {myCampaigns.data && myCampaigns.data.length > 0 && (
                <div className="card">
                    <h2 className="card__title">My campaigns</h2>
                    <div className="toolbar">
                        {myCampaigns.data.slice(0, 8).map((c) => (
                            <button
                                key={c.id}
                                className={`btn btn--small${c.id === activeId ? ' btn--primary' : ''}`}
                                disabled={fetchMutation.isPending}
                                onClick={() => pick(c.id)}
                            >
                                {c.name} · #{c.id}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            <div className="toolbar">
                <input
                    className="input"
                    inputMode="numeric"
                    placeholder="Campaign ID"
                    value={input}
                    onChange={(e) => setInput(e.target.value.replace(/\D/g, ''))}
                />
                <button className="btn btn--primary" disabled={!canFetch} onClick={() => fetchMutation.mutate(id)}>
                    {fetchMutation.isPending ? 'Loading…' : 'Fetch Streams'}
                </button>
            </div>

            {activeId !== null && (
                <p className="muted">
                    Campaign #{activeId}
                    {title && `: ${title}`}
                </p>
            )}

            {saved.isLoading && <p className="muted">Loading saved streams…</p>}

            {activeId !== null && !saved.isLoading && streams.length === 0 && (
                <p className="muted">Nothing is saved for this campaign yet. Press Fetch Streams.</p>
            )}

            {streams.map((s) => (
                <StreamCard key={s.id} stream={s} onUpdate={replaceStream} />
            ))}
        </>
    )
}