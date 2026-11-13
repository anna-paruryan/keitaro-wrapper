import { useState } from 'react'
import { Toaster } from 'sonner'
import CreateCampaign from '@/pages/CreateCampaign'
import CampaignEditor from '@/pages/CampaignEditor'

type Tab = 'create' | 'editor'

export default function App() {
    const [tab, setTab] = useState<Tab>('create')

    const tabClass = (name: Tab) => (tab === name ? 'tab tab--active' : 'tab')

    return (
        <>
            <Toaster position="top-right" richColors />

            <header className="header">
                <button className={tabClass('create')} onClick={() => setTab('create')}>
                    Create campaign
                </button>
                <button className={tabClass('editor')} onClick={() => setTab('editor')}>
                    Editor
                </button>
            </header>

            <main className="container">
                <div hidden={tab !== 'create'}>
                    <CreateCampaign />
                </div>
                <div hidden={tab !== 'editor'}>
                    <CampaignEditor />
                </div>
            </main>
        </>
    )
}