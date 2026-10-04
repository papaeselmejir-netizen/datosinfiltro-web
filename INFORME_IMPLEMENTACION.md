# Informe de implementación: DatoSinFiltro

Fecha: 4 de octubre de 2026.

## Estado

El proyecto ya tiene un flujo local y programado que investiga noticias, redacta borradores, exige dos fuentes con texto extraído, dos imágenes con licencia y un video relacionado, y publica automáticamente los artículos que cumplen las reglas. La web resultante es estática y está configurada para Vercel.

**La versión nueva ya está publicada en Vercel.** Los secretos de Gemini y Pexels ya están configurados en GitHub Actions. Las ejecuciones manuales [#110](https://github.com/papaeselmejir-netizen/datosinfiltro-web/actions/runs/37176448080), [#111](https://github.com/papaeselmejir-netizen/datosinfiltro-web/actions/runs/37177133245) y [#112](https://github.com/papaeselmejir-netizen/datosinfiltro-web/actions/runs/37177528310) terminaron sin errores técnicos, pero las noticias nuevas fallaron la auditoría posterior: una mezcló Muse Gadgets con un generador de imágenes, otra confundió escuelas de cine e inteligencia artificial en San Marcos y la tercera trató dos copias de un despacho de agencia como fuentes independientes. Las tres notas se retiraron de `published/`, del sitio y de los sitemaps. Se reforzó la comprobación del asunto central y se añadió detección de titulares y textos sindicados. El sistema conserva la noticia verificada anterior.

La ejecución [#113](https://github.com/papaeselmejir-netizen/datosinfiltro-web/actions/runs/37177922908), ya con estos controles, terminó correctamente y no publicó noticias nuevas. El repositorio mantuvo una sola noticia validada. Este resultado muestra un comportamiento conservador, pero también que el volumen actual todavía es insuficiente para una estrategia de monetización.

## Búsqueda por categoría y región

El cupo de búsqueda vuelve a ser **tres candidatas sobre Perú y tres del extranjero por categoría**. Hubo una configuración intermedia de dos y dos; se corrigió. El país de la interfaz de Google News no demuestra dónde ocurrió una noticia: la búsqueda de Perú ahora añade lugares peruanos y verifica el titular o resumen; la búsqueda internacional excluye los asuntos identificados como peruanos. El filtro elimina guías para ver transmisiones, resultados de redes sociales, notas de más de cuatro días y titulares duplicados. Se consultan hasta 18 resultados de Google News por región para completar tres candidatas recientes de medios distintos. Si un RSS local falla, se continúa con Google News; GNews y Currents son respaldos opcionales cuando hay claves válidas.

El objetivo de seis se refiere a **candidatas investigadas**, no a seis publicaciones garantizadas. Actualmente se permite como máximo un borrador verificado por categoría y ocho por ejecución. Publicar exige fuentes independientes y multimedia relacionada con licencia; una categoría puede terminar con menos de tres candidatas o con ningún artículo si las fuentes no cumplen los controles. La clasificación geográfica por titular es conservadora y aún puede requerir auditoría humana en noticias ambiguas.

En una consulta real del 4 de octubre, el buscador completó 3 + 3 en las ocho categorías. El resultado cambia con los feeds; esta comprobación demuestra capacidad de búsqueda, no valida por sí sola los hechos ni promete 48 publicaciones.

## Flujo implementado

1. GitHub Actions ejecuta `main.py` a las 06:00, 12:00, 18:00 y 22:00, hora de Perú.
2. El recolector consulta RSS de medios, Google News y las API configuradas. Se ordenan los candidatos por actualidad y se descartan titulares de tráfico fácil.
3. Cada candidato debe aportar texto extraído de al menos dos dominios con cobertura independiente. Se descartan titulares idénticos de distintos medios y textos sindicados casi iguales. Se corrigió el decodificador de Google News, que había cambiado su campo de respuesta.
4. Se buscan imágenes de Pexels y, si faltan, de Wikimedia Commons. Se registra autor, fuente y licencia; los filtros evitan coincidencias geográficas erróneas. Se buscan videos específicos en YouTube; si no hay uno apropiado o se agota su cuota, Pexels ofrece un clip temático que se identifica como ilustración.
5. Gemini redacta a partir del contexto obtenido y una segunda comprobación rechaza afirmaciones no sustentadas. La corroboración y el texto final deben conservar el aspecto específico del producto cuando coinciden nombres de productos distintos. El sistema omite un candidato cuando faltan fuentes o multimedia; nunca añade material arbitrario para completar una noticia.
6. `publish_verified.py` mueve los artículos válidos a `published/`, genera el sitio en un directorio temporal y sustituye las páginas después de una compilación correcta. Los JSON publicados quedan versionados para conservar el historial entre ejecuciones.
7. GitHub Actions hace commit y push de artículos y páginas. La integración Git de Vercel debe desplegar la rama de producción. `vercel.json` apunta a `website/public`.

## Sitio y CMS

- Portada, ocho categorías, búsqueda local, tema claro/oscuro, diseño adaptable, páginas «Quiénes somos», «Política editorial» y «Privacidad».
- Cada artículo nuevo muestra fecha real, resumen, fuentes, dos imágenes con créditos/licencias y video con su procedencia. Las imágenes y videos de archivo se etiquetan como ilustrativos.
- Metadatos Open Graph, datos estructurados `NewsArticle`, URLs estables, `robots.txt`, sitemap general y sitemap de noticias. El dominio canónico configurado es `https://datosinfiltro-web.vercel.app`.
- El CMS exige contraseña, comprueba origen de las peticiones, valida rutas de borradores y publica mediante una construcción temporal. Debe ejecutarse en un servidor persistente con HTTPS; el sitio estático de Vercel no necesita el CMS para actualizarse mediante GitHub Actions.

## Pruebas realizadas

- Dieciocho pruebas Python: control editorial, fuentes, búsqueda de tres asuntos peruanos por categoría, filtro geográfico, actualidad, descarte de redes sociales y guías, detección de despachos sindicados, desambiguación de productos y especialidades, URLs privadas, decodificación de Google News, conservación de artículos entre ejecuciones, generación del sitio, API de video Pexels y selección de archivo por tema específico.
- `npm run lint`, `npx tsc --noEmit` y `npm run build` del CMS finalizaron correctamente. Next.js muestra una advertencia sobre trazado dinámico de archivos, sin impedir la compilación.
- Prueba real con noticias de Lima: se obtuvo un borrador sobre los conciertos de BTS a partir de tres medios, dos imágenes de tráfico de Lima con licencia Pexels y un video específico de El Comercio. Se generó un checkout de despliegue aislado con ese artículo, portada y ocho categorías, conservando intactos los cambios anteriores del checkout principal.
- Se inspeccionó visualmente la portada y el artículo generados en un servidor local. Se corrigió la navegación, que ocupaba varias líneas.
- La nueva clave de Pexels respondió HTTP 200. Se corrigió la ruta de su API de video y se probaron búsquedas reales para desvíos en Lima, tecnología universitaria, Premios Ariel y producción cinematográfica. YouTube devolvió HTTP 429 por límite de solicitudes, por lo que Pexels actuó como respaldo. Las ejecuciones #110–#112 probaron que el flujo escribe en GitHub y despliega en Vercel; las notas nuevas se retiraron tras detectar errores editoriales. Esta revisión evidencia que el flujo no debe considerarse todavía suficientemente fiable para monetización sin auditorías periódicas.

## Pasos externos pendientes

1. Facilitar un correo editorial público y guardarlo como variable `CONTACT_EMAIL` del repositorio para mostrar contacto y correcciones. Actualmente no se publica ningún correo inventado.
2. Rotar la clave de YouTube que apareció en un registro de error durante las pruebas. Las claves `GNEWS_API_KEY` y `CURRENTS_API_KEY` son opcionales; la instancia local de GNews respondió HTTP 400, por lo que conviene revisarla o desactivarla.
3. Revisar el contenido histórico. Los 144 JSON antiguos de `output/` carecen de trazabilidad suficiente de derechos y no se vuelven a publicar. Permanecen recuperables en Git.
4. Para AdSense: solicitar aprobación, aportar un identificador `ADSENSE_PUBLISHER_ID` real, actualizar la política de privacidad y el consentimiento de cookies cuando proceda, e integrar el código de anuncios solo después de la aprobación. El sistema no garantiza aprobación ni ingresos.

## Seguridad y riesgos operativos

- Se retiró una credencial que estaba incrustada en la URL remota local de Git. Ese token debe revocarse y reemplazarse en GitHub.
- Una clave de YouTube apareció en la salida de un error HTTP durante la prueba; se cambió el registro de errores para que no vuelva a imprimirse. Conviene rotar esa clave y restringir la nueva a la API y al entorno necesarios.
- Los controles automáticos reducen errores, pero una noticia puede requerir corrección humana. El CMS permite revisión manual y cada artículo revela si la tuvo.
- Pexels y Wikimedia ofrecen contenido reutilizable bajo condiciones concretas. Su procedencia y licencia se conservan en el JSON y se muestran en la noticia. Los clips de archivo no se presentan como imágenes del acontecimiento.

## Objetivo de monetización

Prioridad inmediata: ampliar el catálogo de fuentes originales y comprobar durante varios días cuántos asuntos tienen dos coberturas realmente independientes. En las tres primeras publicaciones automáticas nuevas hubo fallos editoriales; tras reforzar las reglas, la siguiente ejecución publicó cero. Por ello, **el sistema no está todavía listo para monetización sin supervisión editorial periódica**, aunque la infraestructura de publicación funciona. Después, enviar el sitemap a Search Console, medir indexación, tráfico orgánico y velocidad de página, habilitar un canal de correcciones y solicitar AdSense. Google exige una política de privacidad que describa cookies y tratamiento de datos cuando se usan sus anuncios: [contenido requerido](https://support.google.com/adsense/answer/1348695?hl=es), [políticas de editores](https://support.google.com/adsense/answer/10502938?hl=es). La [licencia de Pexels](https://www.pexels.com/license/) permite uso comercial bajo sus condiciones; la [configuración de Vercel](https://vercel.com/docs/project-configuration/vercel-json) define el directorio público y los [despliegues Git](https://vercel.com/docs/git) se activan por push.
