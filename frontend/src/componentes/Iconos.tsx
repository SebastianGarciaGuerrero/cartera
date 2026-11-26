// Íconos del menú: trazos simples en SVG (sin librerías). Heredan el color
// del texto (currentColor), así sirven en el menú oscuro y en fondos claros.

const TRAZOS = {
  inicio: ['M3 11l9-8 9 8', 'M5 10v10h5v-6h4v6h5V10'],
  calendario: ['M4 5h16v16H4z', 'M16 3v4M8 3v4M4 10h16', 'M8 14h2M14 14h2M8 17h2'],
  grafico: ['M4 20V11', 'M10 20V5', 'M16 20v-6', 'M2 20h20'],
  cartera: ['M3 7.5A1.5 1.5 0 0 1 4.5 6H9l2 2h8.5A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z'],
  personas: ['M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20', 'M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z',
    'M20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35', 'M15 4.2a3.5 3.5 0 0 1 0 6.6'],
  billetera: ['M3 7h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M3 7l12-3.5V7', 'M16.5 13.5h.01'],
  calculadora: ['M6 2.5h12a1.5 1.5 0 0 1 1.5 1.5v16a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 20V4A1.5 1.5 0 0 1 6 2.5z',
    'M8 6.5h8v3H8z', 'M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 17h.01M12 17h.01M15.5 17h.01'],
  balanza: ['M12 3v18', 'M7 21h10', 'M5 7h14', 'M5 7l-3 6.5a3 3 0 0 0 6 0z', 'M19 7l-3 6.5a3 3 0 0 0 6 0z'],
  documento: ['M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z', 'M14 3v5h5', 'M8.5 13h7M8.5 17h4'],
  recibo: ['M6 2.5h12v19l-3-2-3 2-3-2-3 2z', 'M9 7h6M9 11h6M9 15h3.5'],
  mas: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 8v8M8 12h8'],
  subir: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 15v4.5A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5V15'],
  informe: ['M4.5 3h15v18h-15z', 'M8 8h8M8 12h8M8 16h5'],
  edificio: ['M4 21V4.5A1.5 1.5 0 0 1 5.5 3h8A1.5 1.5 0 0 1 15 4.5V21', 'M15 9h3.5A1.5 1.5 0 0 1 20 10.5V21', 'M2 21h20',
    'M8 7h3M8 11h3M8 15h3'],
  usuario: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21a8 8 0 0 1 16 0'],
  maletin: ['M3 8h18v12H3z', 'M8 8V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2', 'M3 13h18'],
  engranaje: ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
    'M12 2.5v2.5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8'],
  flecha: ['M9 6l6 6-6 6'],
} as const

export type NombreIcono = keyof typeof TRAZOS

export function Icono({ nombre, className = 'icono' }: { nombre: NombreIcono; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none"
      stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {TRAZOS[nombre].map((d) => <path key={d} d={d} />)}
    </svg>
  )
}
