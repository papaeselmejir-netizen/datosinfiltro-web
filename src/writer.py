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


def generate_multi_channel_content(tema, contexto, categoria, web_url=None, region=None):
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

    prompt = f"""
    Eres un equipo experto de redactores compuesto por un Periodista Web, un Community Manager y un Guionista de TikTok.
    Tu tarea es crear contenido multi-canal sobre las noticias de la categoria "{categoria}".

    REGLAS ESTRICTAS:
    - NO INVENTES DATOS, citas, cifras, fechas ni declaraciones. Usa SOLO el contexto proporcionado.
    - Si las fuentes discrepan, explica la discrepancia y no presentes el dato como confirmado.
    - No copies párrafos de las fuentes; aporta una síntesis propia con contexto y utilidad.
    - Evita sensacionalismo, promesas de contenido oculto y afirmar que algo está ocurriendo EN VIVO sin prueba.
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
    3. articulo_web: Párrafos cortos, subtítulos útiles, antecedentes y límites de lo conocido. No añadas relleno.
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
                "Compara el artículo con el contexto de fuentes. Marca supported=false si hay "
                "cualquier cifra, fecha, cargo, declaración, resultado o hecho concreto que no esté "
                "respaldado explícitamente. No uses conocimiento externo.\n\n"
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
