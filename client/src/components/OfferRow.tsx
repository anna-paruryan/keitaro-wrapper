import type { StreamOffer } from '@/types'

interface Props {
    offer: StreamOffer
    busy: boolean // a request of this stream is in progress: all its buttons are disabled
    onRemove: () => void
    onRestore: () => void
    onTogglePin: () => void
}

export default function OfferRow({ offer, busy, onRemove, onRestore, onTogglePin }: Props) {
    return (
        <div className={`offer-row offer-row--${offer.status}`}>
            <div className="offer-row__name">
                {offer.status !== 'active' && <span className={`tag tag--${offer.status}`}>{offer.status}</span>}
                {offer.name}
            </div>

            <div className="offer-row__controls">
                <span className="offer-row__share">{offer.share}%</span>

                {offer.status === 'removed' ? (
                    <button className="btn btn--small" disabled={busy} onClick={onRestore}>
                        Bring Back
                    </button>
                ) : (
                    <>
                        <button
                            className={`btn btn--small${offer.pinned ? ' btn--pin-on' : ''}`}
                            disabled={busy}
                            aria-pressed={offer.pinned}
                            title="Pinned share does not change when offers are added or removed"
                            onClick={onTogglePin}
                        >
                            {offer.pinned ? 'Pinned' : 'Pin'}
                        </button>
                        <button className="btn btn--small btn--danger" disabled={busy} onClick={onRemove}>
                            Remove
                        </button>
                    </>
                )}
            </div>
        </div>
    )
}