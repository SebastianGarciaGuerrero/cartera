// Marca del PRODUCTO (el software), centralizada en un solo lugar.
// Es lo que se ve en el login y en el título de la pestaña.
//
// Ojo con la diferencia:
//   MARCA   → cómo se llama el sistema (esto).
//   empresa → quién lo usa: razón social, membrete, fonos y dirección que
//             salen en los documentos Word. Eso NO se toca acá, se edita
//             desde Configuración → Mi empresa (tabla `empresa` en la DB).
export const MARCA = {
  nombre: 'Cartera',                      // nombre corto (wordmark)
  eslogan: 'Gestión y recupero de cobranzas',
}
