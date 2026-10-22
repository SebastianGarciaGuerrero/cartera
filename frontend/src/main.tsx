import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './estilos.css'
import './estilos-trabajo.css'
import App from './App.tsx'
import { adaptadorListo } from './api/client'

// TanStack Query maneja el cache de datos del servidor: evita pedir lo mismo
// dos veces y refresca solo cuando corresponde.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

// En modo demo esperamos a que el backend simulado esté instalado antes de
// montar la app (en modo normal la promesa ya está resuelta, no espera nada).
adaptadorListo.then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  )
})
