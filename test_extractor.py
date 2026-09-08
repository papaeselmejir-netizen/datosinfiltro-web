"""Test rapido del pipeline paso a paso."""
import asyncio
import sys
import os

# Forzar UTF-8 en la consola de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Forzar flush en cada print
import functools
print = functools.partial(print, flush=True)

print("=" * 50)
print("  TEST DEL PIPELINE - EXTRACTOR + CRAWLER")
print("=" * 50)

print("\n1. Importando modulos...")
from src.extractor import extract_news_multi_source, NEWS_LANG, NEWS_COUNTRY
from src.crawler import investigate_news
print("   OK")

print(f"\n   Idioma: {NEWS_LANG} | Pais: {NEWS_COUNTRY}")

print("\n2. Extrayendo noticias de multiples fuentes (Tecnologia)...")
noticias = extract_news_multi_source("Tecnologia, Gadgets e Inteligencia Artificial")
print(f"   {len(noticias)} noticias extraidas")
for n in noticias:
    print(f"   - [{n.get('origen', '?')}] {n['titulo'][:70]}")
    if n.get("snippet"):
        print(f"     Snippet: {n['snippet'][:100]}...")

print("\n3. Decodificando URLs y extrayendo contenido...")

async def test():
    contexto = await investigate_news(noticias)
    print(f"\n4. Contexto total: {len(contexto)} caracteres")
    print(f"   Preview: {contexto[:300]}...")
    return contexto

asyncio.run(test())
print("\nTest completado!")
