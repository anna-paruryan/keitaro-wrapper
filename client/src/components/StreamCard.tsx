import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import { addOffer, cancelStream, pinOffer, pushStream, removeOffer, restoreOffer } from '@/api/editor'
import OfferRow from '@/components/OfferRow'
import OfferSearch from '@/components/OfferSearch'
import type { OfferShort, Stream } from '@/types'

interface Props {
    stream: Stream
    onUpdate: (stream: Stream) => void // the server returns the updated stream: the parent puts it in place of the old one
}

export default function StreamCard({ stream, onUpdate }: Props) {
    // Changing this number re-creates the search field, so it becomes empty after an offer is added
    const [searchKey, setSearchKey] = useState(0)

    const add = useMutation({
        mutationFn: (offer: OfferShort) => addOffer(stream.id, offer.id),
        onSuccess: (updated) => {
            onUpdate(updated)
            setSearchKey((k) => k + 1)
        },
    })
    const remove = useMutation({
        mutationFn: (offerId: number) => removeOffer(stream.id, offerId),
        onSuccess: (updated) => onUpdate(updated),
    })
    const restore = useMutation({
        mutationFn: (offerId: number) => restoreOffer(stream.id, offerId),
        onSuccess: (updated) => onUpdate(updated),
    })
    const pin = useMutation({
        mutationFn: (v: { offerId: number; pinned: boolean }) => pinOffer(stream.id, v.offerId, v.pinned),
        onSuccess: (updated) => onUpdate(updated),
    })
    const push = useMutation({
        mutationFn: () => pushStream(stream.id),
        onSuccess: (updated) => {
            onUpdate(updated)
            toast.success('Stream pushed to Keitaro')
        },
    })
    const cancel = useMutation({
        mutationFn: () => cancelStream(stream.id),
        onSuccess: (updated) => onUpdate(updated),
    })

    // Every action recalculates the shares of the whole stream, so two clicks at once could clash.
    const busy =
        add.isPending || remove.isPending || restore.isPending || pin.isPending || push.isPending || cancel.isPending

    // Keitaro does not accept a stream without offers: Push stays disabled until one is active
    const hasLiveOffers = stream.offers.some((o) => o.status !== 'removed')

    return (
        <section className={`stream${stream.dirty ? ' stream--dirty' : ''}`}>
            <header className="stream__head">
                <div>
                    <h2 className="stream__title">{stream.name}</h2>
                    <div className="stream__meta">
                        Position {stream.position} · Stream ID {stream.id}
                    </div>
                </div>

                <div className="stream__actions">
                    {stream.dirty && (
                        <>
                            <span className="tag tag--new">Unpublished</span>
                            <button className="btn btn--small" disabled={busy} onClick={() => cancel.mutate()}>
                                Cancel
                            </button>
                            <button
                                className="btn btn--small btn--primary"
                                disabled={busy || !hasLiveOffers}
                                title={hasLiveOffers ? 'Send these changes to Keitaro' : 'Add or bring back an offer first'}
                                onClick={() => push.mutate()}
                            >
                                {push.isPending ? 'Pushing…' : 'Push to KT'}
                            </button>
                        </>
                    )}
                </div>
            </header>

            {stream.has_offers ? (
                <>
                    {stream.offers.map((o) => (
                        <OfferRow
                            key={o.offer_id}
                            offer={o}
                            busy={busy}
                            onRemove={() => remove.mutate(o.offer_id)}
                            onRestore={() => restore.mutate(o.offer_id)}
                            onTogglePin={() => pin.mutate({ offerId: o.offer_id, pinned: !o.pinned })}
                        />
                    ))}

                    <div className="stream__footer">
                        <div className="field">
                            <label>Add offer to this stream</label>
                            <OfferSearch
                                key={searchKey}
                                value={null}
                                onChange={(offer) => {
                                    if (offer && !busy) add.mutate(offer)
                                }}
                            />
                            <span className="muted">
                                Click a result to add it. Nothing reaches Keitaro until you press Push to KT.
                            </span>
                        </div>
                    </div>
                </>
            ) : (
                <p className="stream__empty">No offers in this stream</p>
            )}
        </section>
    )
}