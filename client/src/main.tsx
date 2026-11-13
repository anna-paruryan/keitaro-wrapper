import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import './index.css'
import App from '@/App'

const showError = (e: Error) => toast.error(e.message, { id: 'api-error' })

const queryClient = new QueryClient({
    queryCache: new QueryCache({ onError: showError }),
    mutationCache: new MutationCache({ onError: showError }),
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
})

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        <QueryClientProvider client={queryClient}>
            <App />
        </QueryClientProvider>
    </StrictMode>,
)