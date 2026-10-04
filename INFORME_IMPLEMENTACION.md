# Informe de implementación: DatoSinFiltro

Fecha: 3 de octubre de 2026.

## Estado

El proyecto ya tiene un flujo local y programado que investiga noticias, redacta borradores, exige dos fuentes con texto extraído, dos imágenes con licencia y un video relacionado, y publica automáticamente los artículos que cumplen las reglas. La web resultante es estática y está configurada para Vercel.

**La versión nueva ya está publicada en Vercel.** GitHub exige verificación por correo antes de guardar los secretos nuevos de Gemini y Pexels. El sitio público muestra una noticia verificada con dos imágenes y video. La automatización remota está programada; falta comprobar una ejecución exitosa con las claves actualizadas.

## Flujo implementado

1. GitHub Actions ejecuta `main.py` a las 06:00, 12:00, 18:00 y 22:00, hora de Perú.
2. El recolector consulta RSS de medios, Google News y las API configuradas. Se ordenan los candidatos por actualidad y se descartan titulares de tráfico fácil.
3. Cada candidato debe aportar texto extraído de al menos dos dominios. Se corrigió el decodificador de Google News, que había cambiado su campo de respuesta.
4. Se buscan imágenes de Pexels y, si faltan, de Wikimedia Commons. Se registra autor, fuente y licencia; los filtros evitan coincidencias geográficas erróneas. Se buscan videos específicos en YouTube; si no hay uno apropiado o se agota su cuota, Pexels ofrece un clip temático que se identifica como ilustración.
5. Gemini redacta a partir del contexto obtenido y una segunda comprobación rechaza afirmaciones no sustentadas. El sistema omite un candidato cuando faltan fuentes o multimedia; nunca añade material arbitrario para completar una noticia.
6. `publish_verified.py` mueve los artículos válidos a `published/`, genera el sitio en un directorio temporal y sustituye las páginas después de una compilación correcta. Los JSON publicados quedan versionados para conservar el historial entre ejecuciones.
7. GitHub Actions hace commit y push de artículos y páginas. La integración Git de Vercel debe desplegar la rama de producción. `vercel.json` apunta a `website/public`.

## Sitio y CMS

- Portada, ocho categorías, búsqueda local, tema claro/oscuro, diseño adaptable, páginas «Quiénes somos», «Política editorial» y «Privacidad».
- Cada artículo nuevo muestra fecha real, resumen, fuentes, dos imágenes con créditos/licencias y video con su procedencia. Las imágenes y videos de archivo se etiquetan como ilustrativos.
- Metadatos Open Graph, datos estructurados `NewsArticle`, URLs estables, `robots.txt`, sitemap general y sitemap de noticias. El dominio canónico configurado es `https://datosinfiltro-web.vercel.app`.
- El CMS exige contraseña, comprueba origen de las peticiones, valida rutas de borradores y publica mediante una construcción temporal. Debe ejecutarse en un servidor persistente con HTTPS; el sitio estático de Vercel no necesita el CMS para actualizarse mediante GitHub Actions.

## Pruebas realizadas

- Ocho pruebas Python: control editorial, fuentes, URLs privadas, decodificación de Google News, conservación de artículos entre ejecuciones, generación del sitio y video Pexels.
- `npm run lint`, `npx tsc --noEmit` y `npm run build` del CMS finalizaron correctamente. Next.js muestra una advertencia sobre trazado dinámico de archivos, sin impedir la compilación.
- Prueba real con noticias de Lima: se obtuvo un borrador sobre los conciertos de BTS a partir de tres medios, dos imágenes de tráfico de Lima con licencia Pexels y un video específico de El Comercio. Se generó un checkout de despliegue aislado con ese artículo, portada y ocho categorías, conservando intactos los cambios anteriores del checkout principal.
- Se inspeccionó visualmente la portada y el artículo generados en un servidor local. Se corrigió la navegación, que ocupaba varias líneas.
- La nueva clave de Pexels respondió HTTP 200. Gemini y YouTube respondieron correctamente en pruebas previas; YouTube devolvió luego HTTP 429 por límite de solicitudes. El respaldo de Pexels evita que ese límite obligue a usar un video irrelevante.

## Pasos externos pendientes

1. Terminar la verificación por correo de GitHub y actualizar los secretos `GEMINI_API_KEY` y `PEXELS_API_KEY` en **Settings → Secrets and variables → Actions**. `YOUTUBE_API_KEY` ya existe, pero conviene rotarla porque apareció en un registro de error durante las pruebas. Los `.env` locales están ignorados por Git y no llegan a Actions. Las claves `GNEWS_API_KEY` y `CURRENTS_API_KEY` son opcionales; la instancia local de GNews respondió HTTP 400, por lo que conviene revisarla o desactivarla.
2. Ejecutar manualmente el nuevo workflow de GitHub Actions y verificar que genere y publique noticias. La conexión GitHub–Vercel quedó confirmada por el despliegue de la portada y el artículo nuevo.
3. Facilitar un correo editorial público y guardarlo como variable `CONTACT_EMAIL` del repositorio para mostrar contacto y correcciones. Actualmente no se publica ningún correo inventado.
4. Revisar el contenido histórico. Los 144 JSON antiguos de `output/` carecen de trazabilidad suficiente de derechos y no se vuelven a publicar. Al generarse el primer sitio nuevo, las páginas HTML antiguas salen de la versión publicada; permanecen recuperables en Git. Es una decisión de calidad y licencias que conviene revisar antes del primer despliegue automático.
5. Para AdSense: solicitar aprobación, aportar un identificador `ADSENSE_PUBLISHER_ID` real, actualizar la política de privacidad y el consentimiento de cookies cuando proceda, e integrar el código de anuncios solo después de la aprobación. El sistema no garantiza aprobación ni ingresos.

## Seguridad y riesgos operativos

- Se retiró una credencial que estaba incrustada en la URL remota local de Git. Ese token debe revocarse y reemplazarse en GitHub.
- Una clave de YouTube apareció en la salida de un error HTTP durante la prueba; se cambió el registro de errores para que no vuelva a imprimirse. Conviene rotar esa clave y restringir la nueva a la API y al entorno necesarios.
- Los controles automáticos reducen errores, pero una noticia puede requerir corrección humana. El CMS permite revisión manual y cada artículo revela si la tuvo.
- Pexels y Wikimedia ofrecen contenido reutilizable bajo condiciones concretas. Su procedencia y licencia se conservan en el JSON y se muestran en la noticia. Los clips de archivo no se presentan como imágenes del acontecimiento.

## Objetivo de monetización

Prioridad inmediata: activar el flujo remoto, corregir fuentes/API que fallen y mantener una proporción alta de noticias originales con fuentes comprobables. Después, enviar el sitemap a Search Console, medir indexación, tráfico orgánico y velocidad de página, habilitar un canal de correcciones y solicitar AdSense. Google exige una política de privacidad que describa cookies y tratamiento de datos cuando se usan sus anuncios: [contenido requerido](https://support.google.com/adsense/answer/1348695?hl=es), [políticas de editores](https://support.google.com/adsense/answer/10502938?hl=es). La [licencia de Pexels](https://www.pexels.com/license/) permite uso comercial bajo sus condiciones; la [configuración de Vercel](https://vercel.com/docs/project-configuration/vercel-json) define el directorio público y los [despliegues Git](https://vercel.com/docs/git) se activan por push.
