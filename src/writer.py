import os
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# Configurar cliente con API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

client = genai.Client(api_key=GEMINI_API_KEY)

WEB_URL_PLACEHOLDER = os.getenv("SITE_URL", "")


# Esquema de salida estructurado
class ContentOutput(BaseModel):
    titulo_articulo: str = Field(
        description="Titulo atractivo y optimizado para SEO. Sin formato H1, solo el texto del titulo."
    )
    articulo_web: str = Field(
        description="Artículo periodístico claro en Markdown. Distingue hechos confirmados de contexto; no inventes ni rellenes datos. No incluyas H1."
    )
    resumen: str = Field(description="Resumen factual de máximo 160 caracteres, sin emojis ni clickbait.")
    hilo_x: str = Field(
        description="Hilo de 3 a 5 tweets separados por saltos de linea. Urgente, incisivo, con datos duros. Maximo 3 emojis. El ultimo tweet debe incluir un CTA con enlace al sitio web."
    )
    post_facebook: str = Field(
        description="Publicación fiel a los hechos. Resume lo importante sin promesas engañosas y enlaza al artículo si hay URL configurada."
    )
    guion_tiktok: str = Field(
        description="Guion de 45-60 segundos. Estructura: 0-3s gancho provocativo, 3-45s explicacion dinamica, 45-60s pregunta y CTA final diciendo EXPRESAMENTE 'Tienes el link con la noticia completa en mi perfil' (NO dictar URLs)."
    )


class QualityOutput(BaseModel):
    supported: bool = Field(description="True solo si cada dato concreto del artículo está respaldado por el contexto.")
    unsupported_claims: list[str] = Field(description="Datos, cifras o citas no sustentados por el contexto.")


class ArticleRevision(BaseModel):
    titulo_articulo: str
    resumen: str
    articulo_web: str


class SourceCoverageOutput(BaseModel):
    independent: bool = Field(description="Ambos textos aportan cobertura factual independiente del mismo hecho.")
    reason: str = Field(description="Motivo concreto y breve de la decisión.")


class PrimaryAnnouncementOutput(BaseModel):
    eligible: bool = Field(description="True únicamente para una nota atribuida a la acción o anuncio propio de la institución.")
    claims_requiring_independent_source: list[str] = Field(description="Afirmaciones concretas que no puede acreditar el comunicado por sí solo.")
    reason: str = Field(description="Motivo concreto y breve de la decisión.")


def verify_primary_announcement(content, context):
    """A single official page may establish its own announcement, not outside facts."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                "Decide si una nota puede publicarse usando UNA sola fuente primaria institucional. "
                "eligible=true SOLO si el hecho central es una acción, documento, calendario, "
                "lanzamiento o declaración de la propia institución que publica la fuente; "
                "también un resultado deportivo final publicado por el organizador oficial. "
                "el título, resumen y artículo atribuyen claramente el anuncio a esa entidad; "
                "y cada afirmación externa o cifra se presenta como dato declarado por ella, "
                "sin darlo por verificado de forma independiente. "
                "eligible=false si hay denuncias, acusaciones, delitos, víctimas, daños, "
                "resultados electorales provisionales, eficacia o seguridad médica, "
                "promesas de terceros, interpretaciones controvertidas, una versión disputada "
                "o afirmaciones sobre el mundo que requieren confirmación fuera de la entidad. "
                "Enumera cada afirmación que requiere verificación independiente en "
                "claims_requiring_independent_source y marca eligible=false si la lista no está vacía. "
                "Si parece un resumen promocional sin utilidad periodística, false. "
                "No uses conocimiento externo; ante la duda, false.\n\n"
                f"FUENTE:\n{context}\n\nTÍTULO:\n{content.get('titulo_articulo', '')}"
                f"\n\nRESUMEN:\n{content.get('resumen', '')}"
                f"\n\nARTÍCULO:\n{content.get('articulo_web', '')}"
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PrimaryAnnouncementOutput,
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        result = response.parsed or PrimaryAnnouncementOutput.model_validate_json(response.text)
        if not result.eligible or result.claims_requiring_independent_source:
            print(f"    Fuente primaria insuficiente: {result.reason[:180]}")
            for claim in result.claims_requiring_independent_source[:3]:
                print(f"    Requiere otra fuente: {claim[:160]}")
        return bool(result.eligible and not result.claims_requiring_independent_source)
    except Exception as exc:
        print(f"    No se pudo revisar fuente primaria: {type(exc).__name__}")
        return False


def verify_sources_are_independent(context):
    """Reject two URLs that only repeat one wire dispatch or a generic opinion."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                "Evalúa los DOS textos periodísticos siguientes como fuentes para una noticia. "
                "independent=true solo si ambos confirman el mismo acontecimiento con hechos "
                "concretos suficientes y aportan cobertura o verificación distinguible. "
                "Marca false si el segundo solo parafrasea el mismo despacho de agencia, "
                "repite una cita sin detalles propios, es opinión genérica o contradice "
                "un hecho central. No uses conocimiento externo. En caso de duda, false.\n\n"
                f"TEXTOS:\n{context}"
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SourceCoverageOutput,
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        result = response.parsed or SourceCoverageOutput.model_validate_json(response.text)
        if not result.independent:
            print(f"    Cobertura no independiente: {result.reason[:180]}")
        return bool(result.independent)
    except Exception as exc:
        print(f"    No se pudo comprobar independencia editorial: {type(exc).__name__}")
        return False


def generate_multi_channel_content(tema, contexto, categoria, web_url=None, region=None,
                                   primary_announcement=False):
    """
    Usa Gemini para redactar contenido multi-canal.
    Incluye enlaces de ejemplo al sitio web en los posts de redes sociales.
    :param tema: Tema principal de la noticia.
    :param contexto: Texto completo extraido de las fuentes.
    :param categoria: Categoria (ej. "Tecnologia, Gadgets e IA").
    :param web_url: URL del sitio web donde se publicara. Usa placeholder si es None.
    :param region: Region de la noticia (Mundial o Perú).
    :return: Dict con titulo_articulo, articulo_web, hilo_x, post_facebook, guion_tiktok.
    """
    if web_url is None:
        web_url = WEB_URL_PLACEHOLDER

    region_context = f"\n    REGION DEL ENFOQUE: {region}" if region else ""
    primary_rule = (
        "- Hay UNA fuente primaria institucional. Redacta solo su propio anuncio o acción; "
        "atribúyelo a esa entidad en el título, resumen y cuerpo. No presentes datos "
        "declarados por ella como verificados de manera independiente. Si el anuncio no "
        "permite una nota breve informativa sin relleno, devuelve articulo_web vacío.\n    "
        if primary_announcement else ""
    )
    length_rule = (
        "La nota breve debe tener entre 120 y 220 palabras, solo si la fuente permite "
        "esa extensión sin inventar datos." if primary_announcement else
        "La noticia contrastada debe tener entre 180 y 360 palabras según los datos disponibles."
    )
    category_rules = {
        "Noticias de Ultima Hora y Politica": "Distingue anuncios oficiales de hechos comprobados; cifras electorales, acusaciones y versiones disputadas requieren corroboración independiente.",
        "Salud, Bienestar y Estilo de Vida": "No conviertas resultados preliminares en consejos médicos ni afirmes eficacia o seguridad sin evidencia independiente.",
        "Finanzas, Negocios y Criptomonedas": "Atribuye anuncios de empresas y reguladores; no presentes predicciones, rentabilidad ni movimientos de precio sin datos corroborados.",
        "Deportes en Vivo": "Distingue resultados y calendarios oficiales de rumores de fichajes; no llames final a un marcador parcial.",
        "Tecnologia, Gadgets e Inteligencia Artificial": "Atribuye funciones anunciadas por fabricantes; no conviertas promesas de rendimiento en pruebas independientes.",
        "Gaming y Esports": "Atribuye lanzamientos y cambios anunciados por editores; no inventes reseñas, rendimiento ni experiencia de juego.",
        "Entretenimiento, Farandula y Cine": "Atribuye anuncios del protagonista u organizador; rumores y acusaciones no son hechos confirmados.",
        "Tendencias": "Identifica el hecho concreto detrás de la tendencia; no publiques rumores ni cifras de popularidad sin evidencia.",
    }

    prompt = f"""
    Eres un equipo experto de redactores compuesto por un Periodista Web, un Community Manager y un Guionista de TikTok.
    Tu tarea es crear contenido multi-canal sobre las noticias de la categoria "{categoria}".

    REGLAS ESTRICTAS:
    - NO INVENTES DATOS, citas, cifras, fechas ni declaraciones. Usa SOLO el contexto proporcionado.
    - {length_rule} Usa solo detalles que estén explícitos en las fuentes leídas.
    - {category_rules.get(categoria, '')}
    - Si un detalle aparece en una sola fuente, atribúyelo a ese medio. Omite cifras secundarias que no puedas comprobar.
    - Si las fuentes discrepan, explica la discrepancia y no presentes el dato como confirmado.
    - No copies párrafos de las fuentes; aporta una síntesis propia. No agregues antecedentes externos ni datos para alargar el texto.
    {primary_rule}- Evita sensacionalismo, promesas de contenido oculto y afirmar que algo está ocurriendo EN VIVO sin prueba.
    - Redacta en espanol neutro (latinoamerica).
    - Los posts de redes sociales pueden enlazar al artículo cuando exista una URL pública: {web_url}
    - Adapta el tono a cada plataforma.

    TEMA PRINCIPAL: {tema}
    CATEGORIA: {categoria}{region_context}

    CONTEXTO INVESTIGADO (de fuentes reales):
    {contexto}

    INSTRUCCIONES POR CANAL:
    1. titulo_articulo: Un titulo periodistico atractivo y optimizado para SEO.
    2. resumen: Una oración que responda qué sucedió y por qué importa.
    3. articulo_web: Párrafos cortos, subtítulos solo si ayudan y límites de lo conocido. No añadas relleno.
    4. hilo_x: Hilo de 3-5 posts fieles a la noticia.
    5. post_facebook: Explica el hecho principal sin ocultar información para forzar clics.
    6. guion_tiktok: Guion de 45-60 segundos, informativo y sin dramatización artificial.

    Devuelve un JSON valido con todos los campos del esquema.
    """

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ContentOutput,
                temperature=0.4,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )

        # Usar response.parsed si esta disponible, sino parsear manualmente
        if hasattr(response, "parsed") and response.parsed:
            content_json = response.parsed.model_dump()
        else:
            content_json = json.loads(response.text)

        # Agregar metadata al resultado
        content_json["categoria"] = categoria
        content_json["web_url"] = web_url
        return content_json
    except Exception as e:
        print(f"Error generando contenido con IA: {e}")
        return None


def verify_article_against_sources(article, context):
    """Second-pass source check for the automated publication gate."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                "Compara el título, resumen y artículo con el contexto de fuentes. "
                "Evalúa cada afirmación concreta por separado. Marca supported=false si hay "
                "cualquier cifra, fecha, cargo, declaración, resultado o hecho concreto que no esté "
                "respaldado explícitamente. Revisa de forma específica la temporalidad: si una fuente "
                "dice que algo ocurrirá y el artículo afirma que ya ocurrió, supported=false. "
                "Comprueba también que los subtotales sumen el total "
                "y que las cifras no se contradigan dentro del artículo. No uses conocimiento externo.\n\n"
                f"FUENTES:\n{context}\n\nARTÍCULO:\n{article}"
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QualityOutput,
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        result = response.parsed or QualityOutput.model_validate_json(response.text)
        return bool(result.supported and not result.unsupported_claims)
    except Exception as exc:
        print(f"Error verificando artículo: {exc}")
        return False


def revise_article_against_sources(content, context, primary_announcement=False):
    """One bounded repair pass; the revised text must pass verification again."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=(
                "Corrige este borrador periodístico. Elimina toda afirmación no respaldada "
                "explícitamente por FUENTES, incluidas cifras, fechas, citas y antecedentes. "
                "Respeta el tiempo verbal: un acto futuro no puede redactarse como ya celebrado. "
                "Si un dato consta en una sola fuente, atribúyelo. Comprueba las sumas. "
                + ("Escribe una nota breve de 120 a 220 palabras. Atribuye el anuncio a "
                   "la institución en título, resumen y cuerpo. " if primary_announcement else
                   "Escribe entre 180 y 360 palabras según la evidencia disponible, sin relleno. ") +
                "Si no hay evidencia suficiente, deja articulo_web vacío. No uses conocimiento externo.\n\n"
                f"FUENTES:\n{context}\n\nBORRADOR COMPLETO:\n"
                f"Título: {content.get('titulo_articulo', '')}\n"
                f"Resumen: {content.get('resumen', '')}\n"
                f"Artículo: {content.get('articulo_web', '')}"
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ArticleRevision,
                temperature=0,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        result = response.parsed or ArticleRevision.model_validate_json(response.text)
        return result.model_dump() if result.articulo_web.strip() else None
    except Exception as exc:
        print(f"No se pudo corregir el borrador: {type(exc).__name__}")
        return None


if __name__ == "__main__":
    # Test (Requiere GEMINI_API_KEY en .env)
    print(f"Modelo: {GEMINI_MODEL}")
    test_context = "Amazon anuncio que expandira su servicio de entrega por drones a 500 ciudades de Estados Unidos, incluyendo Chicago y Atlanta. Los drones podran entregar paquetes de hasta 2.3 kg en menos de 30 minutos."
    res = generate_multi_channel_content(
        "Drones de Amazon",
        test_context,
        "Tecnologia, Gadgets e Inteligencia Artificial",
    )
    if res:
        print(json.dumps(res, indent=2, ensure_ascii=False)[:500])
