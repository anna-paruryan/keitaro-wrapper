import {useQuery} from "@tanstack/react-query";
import {getMeta} from "@/api/compaigns.ts";


export default function CreateCampaign() {
    const meta = useQuery({ queryKey: ['meta'], queryFn: getMeta })

    if (meta.isPending) return <p className="muted">Loading…</p>
    if (meta.isError) return <p className="muted">Error: {meta.error.message}</p>

    return (
        <>
            <h1 className="title">Create campaign</h1>
            <pre>{JSON.stringify(meta.data, null, 2)}</pre>
        </>
    )
}