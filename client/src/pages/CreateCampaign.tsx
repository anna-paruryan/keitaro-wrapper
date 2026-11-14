import { Fragment, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createCampaign, getMeta } from '@/api/compaigns.ts'
import OfferSearch from '@/components/OfferSearch'
import type { CreateCampaignResult, Option, OfferShort } from '@/types'

const nameOf = (list: Option[], id: number | null) =>
    list.find((o) => o.id === id)?.name ?? '—'

export default function CreateCampaign() {
    const queryClient = useQueryClient()
    const meta = useQuery({ queryKey: ['meta'], queryFn: getMeta })
    const [name, setName] = useState('')
    const [geo, setGeo] = useState('')
    const [offer, setOffer] = useState<OfferShort | null>(null)
    const [result, setResult] = useState<CreateCampaignResult | null>(null)

    const create = useMutation({
        mutationFn: (chosen: OfferShort) =>
            createCampaign({ name: name.trim(), geo: geo.trim(), offer_id: chosen.id }),
        onMutate: () => setResult(null),
        onSuccess: (data) => {
            setResult(data)
            toast.success(`Campaign ${data.campaign.name} created`)
            // the new campaign appears in the "My campaigns" list of the editor
            queryClient.invalidateQueries({ queryKey: ['my-campaigns'] })
        },
    })

    if (meta.isPending) return <p className="muted">Loading…</p>
    if (meta.isError) return null // тост с ошибкой покажет main.tsx

    const { prefix, domains, groups, sources, defaults } = meta.data
    const notes = Object.values(meta.data.notes ?? {})

    // the user edits the form: the previous error is no longer relevant
    const touch = () => {
        if (create.isError) create.reset()
    }

    const typed = name.trim()
    const fullName = typed.startsWith(prefix) ? typed : `${prefix}${typed}` // the backend adds the prefix only once
    const canCreate = typed !== '' && geo.trim() !== '' && offer !== null && !create.isPending

    return (
        <>
            <h1 className="title">New campaign</h1>
            <p className="hint">
                Visitors from the given countries go to Google, everyone else goes to the chosen offer.
            </p>

            <form
                className="card"
                onSubmit={(e) => {
                    e.preventDefault()
                    if (canCreate && offer) create.mutate(offer)
                }}
            >
                <div className="form-grid">
                    <div className="field">
                        <label htmlFor="name">Name</label>
                        <input
                            id="name"
                            className="input"
                            placeholder="camp1"
                            value={name}
                            onChange={(e) => {
                                touch()
                                setName(e.target.value)
                            }}
                        />
                        <span className="muted">Saved in Keitaro as: {typed ? fullName : `${prefix}…`}</span>
                    </div>

                    <div className="field">
                        <label htmlFor="geo">Geo</label>
                        <input
                            id="geo"
                            className="input"
                            placeholder="MX,AU,RO"
                            value={geo}
                            onChange={(e) => {
                                touch()
                                setGeo(e.target.value)
                            }}
                        />
                        <span className="muted">Two-letter country codes, comma-separated.</span>
                    </div>
                </div>

                <div className="field">
                    <label>Offer</label>
                    <OfferSearch
                        value={offer}
                        onChange={(o) => {
                            touch()
                            setOffer(o)
                        }}
                    />
                    {offer && <span className="muted">Selected: {offer.name}</span>}
                </div>

                <div className="toolbar">
                    <button type="submit" className="btn btn--primary" disabled={!canCreate}>
                        {create.isPending ? 'Creating…' : 'Create'}
                    </button>
                </div>

                {create.isError && (
                    <p className="alert alert--error" role="alert">
                        {create.error.message}
                    </p>
                )}
            </form>

            <div className="card">
                <h2 className="card__title">Campaign settings</h2>
                <dl className="kv">
                    <dt>Domain</dt>
                    <dd>{nameOf(domains, defaults.domain_id)}</dd>
                    <dt>Group</dt>
                    <dd>{nameOf(groups, defaults.group_id)}</dd>
                    <dt>Traffic source</dt>
                    <dd>{nameOf(sources, defaults.traffic_source_id)}</dd>
                </dl>
                {notes.length > 0 && (
                    <details>
                        <summary className="muted">Why these values?</summary>
                        {notes.map((text) => (
                            <p key={text} className="muted">{text}</p>
                        ))}
                    </details>
                )}
            </div>

            {result && (
                <div className="card">
                    <h2 className="card__title">Campaign created</h2>
                    <dl className="kv">
                        <dt>Name</dt>
                        <dd>{result.campaign.name}</dd>
                        <dt>Campaign ID</dt>
                        <dd>{result.campaign.id}</dd>
                        {result.streams.map((s) => (
                            <Fragment key={s.position}>
                                <dt>Stream {s.position}</dt>
                                <dd>{s.title}</dd>
                            </Fragment>
                        ))}
                        {result.campaign.tracker_url && (
                            <>
                                <dt>Link</dt>
                                <dd>{result.campaign.tracker_url}</dd>
                            </>
                        )}
                    </dl>
                    {result.warning && <p className="muted">{result.warning}</p>}
                    <p className="muted">Open the Editor tab to manage the offers of this campaign.</p>
                </div>
            )}
        </>
    )
}