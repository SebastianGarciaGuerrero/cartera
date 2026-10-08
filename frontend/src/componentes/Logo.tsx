import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, ES_DEMO } from '../api/client'

// Logo de la empresa (lo sube cada organización). La imagen se pide con el
// token de la sesión, así que se carga como blob y no con <img src="/api/...">.

export function useLogoEmpresa(tieneLogo: boolean | undefined, version?: string | null) {
  const { data: blob } = useQuery({
    queryKey: ['logo-empresa', version ?? ''],
    enabled: Boolean(tieneLogo) && !ES_DEMO,
    queryFn: async () => (await api.get<Blob>('/empresa/logo', { responseType: 'blob' })).data,
    staleTime: 10 * 60 * 1000,
  })
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!blob || !tieneLogo) { setUrl(null); return }
    const u = URL.createObjectURL(blob)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [blob, tieneLogo])
  return url
}

export function LogoEmpresa({ tieneLogo, version, className, alt }: {
  tieneLogo: boolean | undefined; version?: string | null; className?: string; alt: string
}) {
  const url = useLogoEmpresa(tieneLogo, version)
  if (!url) return null
  return <img src={url} alt={alt} className={className} />
}
