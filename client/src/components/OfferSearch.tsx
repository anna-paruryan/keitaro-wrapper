import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { OfferShort } from '@/types'
import {searchOffers} from "@/api/compaigns.ts";

type Props = {
    value: OfferShort | null
    onChange: (offer: OfferShort | null) => void
}

export default function OfferSearch({ value, onChange }: Props) {
    const [text, setText] = useState('')
    const [debounced, setDebounced] = useState('')
    const [open, setOpen] = useState(false)

    // ждём 300 мс после последней буквы, потом обновляем debounced
    useEffect(() => {
        const timer = setTimeout(() => setDebounced(text.trim()), 300)
        return () => clearTimeout(timer)
    }, [text])

    const offers = useQuery({
        queryKey: ['offers', debounced],
        queryFn: () => searchOffers(debounced),
        enabled: open && debounced.length > 0,
    })

    function pick(offer: OfferShort) {
        onChange(offer)
        setText(offer.name)
        setOpen(false)
    }

    return (
        <div className="ac">
            <input
                className="input"
                placeholder="Search by ID or name…"
                value={text}
                onChange={(e) => {
                    setText(e.target.value)
                    setOpen(true)
                    if (value) onChange(null) // начали печатать заново, прежний выбор сбрасываем
                }}
                onFocus={() => setOpen(true)}
                onBlur={() => setOpen(false)}
            />

            {open && debounced && (
                <ul className="ac__list">
                    {offers.isFetching && <li className="ac__item ac__item--empty">Searching…</li>}
                    {offers.data?.length === 0 && !offers.isFetching && (
                        <li className="ac__item ac__item--empty">Nothing found</li>
                    )}
                    {offers.data?.map((o) => (
                        <li
                            key={o.id}
                            className="ac__item"
                            onMouseDown={(e) => {
                                e.preventDefault() // не даём полю потерять фокус раньше времени
                                pick(o)
                            }}
                        >
                            {o.name}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}