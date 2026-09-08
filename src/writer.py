import os
import json
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# Configurar cliente con API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

client = genai.Client(api_key=GEMINI_API_KEY)

# URL de ejemplo para el sitio web (placeholder hasta que se configure WordPress)
WEB_URL_PLACEHOLDER = "https://www.tu-sitio-noticias.com"


# Esquema de salida estructurado
class ContentOutput(BaseModel):
    titulo_articulo: str = Field(
        description="Titulo atractivo y optimizado para SEO. Sin formato H1, solo el texto del titulo."
    )
    articulo_web: str = Field(
        description="Articulo de 500-800 palabras. OPTIMIZADO PARA ADSENSE: Usa párrafos muy cortos (máximo 3-4 líneas), subtítulos H2, y SIEMPRE incluye al menos una lista con viñetas (bullet points). NO incluir el titulo H1 aqui."
    )
    hilo_x: str = Field(
        description="Hilo de 3 a 5 tweets separados por saltos de linea. Urgente, incisivo, con datos duros. Maximo 3 emojis. El ultimo tweet debe incluir un CTA con enlace al sitio web."
    )
    post_facebook: str = Field(
        description="Publicación de 100-200 palabras. Titulo en mayusculas/emojis. APLICA 'CURIOSITY GAP': Cuenta un 70% de la historia y deja un misterio para obligar al clic. Ej: '...el resultado te sorprenderá'. Finaliza con: Lee la noticia completa aqui: [ENLACE]"
    )
    guion_tiktok: str = Field(
        description="Guion de 45-60 segundos. Estructura: 0-3s gancho provocativo, 3-45s explicacion dinamica, 45-60s pregunta y CTA final diciendo EXPRESAMENTE 'Tienes el link con la noticia completa en mi perfil' (NO dictar URLs)."
    )


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
    - NO INVENTES DATOS. Usa SOLO la informacion del contexto proporcionado.
    - Redacta en espanol neutro (latinoamerica).
    - Los posts de redes sociales DEBEN incluir un CTA (Call to Action) que lleve al lector a la pagina web: {web_url}
    - Adapta el tono a cada plataforma.

    TEMA PRINCIPAL: {tema}
    CATEGORIA: {categoria}{region_context}

    CONTEXTO INVESTIGADO (de fuentes reales):
    {contexto}

    INSTRUCCIONES POR CANAL:
    1. titulo_articulo: Un titulo periodistico atractivo y optimizado para SEO.
    2. articulo_web: Optimizado para AdSense. OBLIGATORIO: Párrafos de máximo 3-4 líneas (para móviles), subtítulos H2, y al menos una lista con viñetas.
    3. hilo_x: Hilo de 3-5 tweets. Datos duros, tono urgente. Ultimo tweet con enlace a {web_url}
    4. post_facebook: Usa Curiosity Gap. No resumas todo, deja un misterio que obligue a hacer clic en el enlace a {web_url}
    5. guion_tiktok: Guion de 45-60 seg. Gancho visual, explicación rápida. El CTA final DEBE decir "Tienes el link con la noticia completa en mi perfil" (nunca dictes la url).

    Devuelve un JSON valido con los 5 campos.
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
