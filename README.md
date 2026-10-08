# DatoSinFiltro

Véase [INFORME_IMPLEMENTACION.md](INFORME_IMPLEMENTACION.md) para el estado de la migración, pruebas y pasos pendientes.

Sistema de noticias con recolección programada, borradores investigados, revisión editorial y publicación estática.

## Publicación automática en Vercel

GitHub Actions investiga las ocho categorías cuatro veces al día y publica los borradores que pasan la comprobación de fuentes, redacción, licencias y pertinencia multimedia. Cada ejecución investiga hasta cinco hechos de Perú y cinco internacionales por categoría; cuando una región no tuvo noticias publicadas en las últimas 24 horas, amplía su búsqueda hasta ocho candidatas y atiende primero las categorías con menos cobertura reciente. Puede aprobar hasta dos noticias por categoría y ejecución. Son topes de búsqueda y publicación, no una cuota garantizada: una noticia sin evidencia o material apropiado no se publica. El resumen de cada ejecución en GitHub Actions muestra la cobertura y las causas de descarte.

La web de producción se genera con `SITE_URL=https://datosinfiltro-web.vercel.app`; una compilación para localhost bloquea deliberadamente la indexación. El servidor local se usa para pruebas y no debe ejecutar un segundo proceso de publicación junto al flujo de GitHub.

Las 24 noticias existentes se revisaron de nuevo con el filtro multimedia y se sustituyeron imágenes o clips que correspondían a otro tema o lugar. Todas las páginas conservan dos imágenes con licencia registrada y un video relacionado; los recursos de archivo se señalan como ilustrativos. La presencia de multimedia y dos fuentes no garantiza por sí sola que una afirmación periodística sea correcta: la política editorial permite corregir o retirar una nota cuando aparezca evidencia nueva.

## Flujo

1. GitHub Actions ejecuta `main.py` cuatro veces al día. Una búsqueda manual también se puede lanzar desde el CMS.
   La búsqueda combina RSS directos, medios especializados definidos por categoría y región en `src/extractor.py`, Google News, Bing News y las API opcionales. Los medios especializados se consultan con búsquedas limitadas a sus dominios; los titulares siguen sujetos a fecha, tema, ubicación del hecho, diversidad de medios y corroboración. Ampliar esta lista no garantiza que haya seis hechos verificables por categoría cada día.
2. Se comparan medios diferentes y se extrae texto suficiente de al menos dos dominios.
3. Se buscan dos imágenes con licencia registrada en Pexels o Wikimedia Commons. Para video se prioriza uno reciente de YouTube que coincida con el hecho; si no existe, se puede usar un clip temático de Pexels claramente marcado como ilustración y con licencia visible.
4. Gemini redacta un borrador y un segundo control comprueba que sus afirmaciones se apoyan en las fuentes. Si fallan las fuentes, la licencia, el video o la longitud mínima, ese candidato se descarta y el bot continúa.
5. `publish_verified.py` publica automáticamente los borradores válidos en `published/` y reconstruye el sitio en un directorio temporal. GitHub Actions guarda los JSON y las páginas en Git. El CMS permite una aprobación humana adicional cuando se ejecuta la búsqueda manual.

Las imágenes y videos de archivo se identifican como **ilustraciones**. Nunca deben hacerse pasar por material del acontecimiento. Si no hay multimedia con licencia y pertinente, la noticia no se publica.

## Configuración

- Crear `.env` desde `.env.example` y completar `GEMINI_API_KEY` y `YOUTUBE_API_KEY`. `PEXELS_API_KEY` es opcional; cuando falta o falla se buscan imágenes en Wikimedia Commons. Para el recolector de GitHub, configurar los secretos con esos mismos nombres en el repositorio; el `.env` local no se sincroniza.
- La publicación programada usa `https://datosinfiltro-web.vercel.app` como dominio canónico. Configurar `CONTACT_EMAIL` como variable de repositorio con un correo editorial real; mientras no exista, el sitio no mostrará un correo inventado. Una compilación manual sin `SITE_URL` crea `robots.txt` con `Disallow: /`. `ADSENSE_PUBLISHER_ID` es una variable opcional posterior.
- Instalar Python 3.11+ y `pip install -r requirements.txt`.
- En `cms_app`, ejecutar `npm ci`, crear `.env.local` con `CMS_ADMIN_PASSWORD` y, si hace falta, `PYTHON_BIN` apuntando al ejecutable de Python. Ejecutar `npm run build` y `npm run start`.
- El CMS usa autenticación HTTP Basic: usuario `editor` y la contraseña de `CMS_ADMIN_PASSWORD`. Publicarlo solo detrás de HTTPS en un servidor persistente con acceso al repositorio y Python. No está diseñado para un entorno sin disco persistente.
- `AUTO_GIT_PUSH=1` en `cms_app/.env.local` activa el commit y push automático tras una aprobación. Usarlo una vez configuradas credenciales Git y una rama de publicación. En este entorno está desactivado hasta preparar esa conexión.
- `ADSENSE_PUBLISHER_ID=pub-...` genera `ads.txt` tras obtener un ID real. El código de anuncios y su ubicación se integran después de la aprobación de AdSense.

La página de privacidad refleja el estado actual sin anuncios. Antes de activar AdSense, hay que añadir un correo editorial verificable, actualizar las divulgaciones de cookies/proveedores, configurar el consentimiento cuando corresponda y revisar el contenido publicado. La aprobación de AdSense y los ingresos dependen de Google y del tráfico real; no los garantiza la automatización.

## Contenido anterior

El generador publica únicamente artículos con `schema_version: 2` que cumplen las validaciones de fuentes, imágenes y video. Los JSON antiguos permanecen en `output/` como archivo para revisión y **no** se borran. Los nuevos JSON de `published/` se guardan en Git para conservar el historial entre ejecuciones. Las páginas HTML antiguas presentes en `website/public/` necesitan una limpieza controlada cuando se migre el sitio al nuevo flujo.

## Comprobaciones

```bash
python -m unittest discover -s tests -v
python publish_verified.py
cd cms_app
npm run lint
npm run build
```

## Despliegue en Vercel

`vercel.json` configura el proyecto para servir `website/public/` como sitio estático. En Vercel, el proyecto debe apuntar a este repositorio y tener **Root Directory** en la raíz del repositorio y la rama de producción correcta. Cada `git push` de GitHub Actions activa un despliegue si la integración Git está conectada. El CMS debe ejecutarse por separado en un servidor persistente con acceso al repositorio; no debe desplegarse como parte del sitio público de Vercel.
