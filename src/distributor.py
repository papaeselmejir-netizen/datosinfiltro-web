import os
import uuid
import asyncio
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler
import logging

load_dotenv()

# Configurar logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Limite de caracteres por mensaje de Telegram
TELEGRAM_MAX_LENGTH = 4096
# Margen para evitar cortar exactamente en el limite
TELEGRAM_SAFE_LENGTH = 4000


def split_long_message(text, max_length=TELEGRAM_SAFE_LENGTH):
    """
    Divide un mensaje largo en multiples partes respetando parrafos.
    Cada parte no excede max_length caracteres.
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break

        # Buscar el ultimo salto de linea doble (separador de parrafos) antes del limite
        chunk = remaining[:max_length]
        split_pos = chunk.rfind("\n\n")

        if split_pos < max_length * 0.3:
            # Si no hay parrafo razonable, buscar salto de linea simple
            split_pos = chunk.rfind("\n")

        if split_pos < max_length * 0.3:
            # Si tampoco hay salto de linea, buscar ultimo espacio
            split_pos = chunk.rfind(" ")

        if split_pos < max_length * 0.3:
            # Ultimo recurso: cortar en el limite
            split_pos = max_length

        parts.append(remaining[:split_pos].strip())
        remaining = remaining[split_pos:].strip()

    return parts


class ContentDistributor:
    def __init__(self):
        self.bot = Bot(token=TELEGRAM_TOKEN)
        self.approval_status = "PENDING"
        self.current_content = None
        self._approval_id = None

    async def _send_long_message(self, text, reply_markup=None):
        """
        Envia un mensaje largo dividiendolo en partes si excede el limite de Telegram.
        Solo el primer mensaje lleva reply_markup (botones), si se proporciona.
        """
        parts = split_long_message(text)

        for i, part in enumerate(parts):
            # Solo el primer fragmento lleva botones
            markup = reply_markup if i == 0 else None
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=part,
                reply_markup=markup,
            )
            if len(parts) > 1 and i < len(parts) - 1:
                await asyncio.sleep(0.3)  # Pequeña pausa entre mensajes

    async def send_for_approval(self, content):
        """
        Envia el contenido al administrador via Telegram y espera aprobacion.
        Envia multiples mensajes para que puedas leer TODO el contenido.
        Cada aprobacion tiene un ID unico para evitar aprobaciones cruzadas.
        """
        self.current_content = content
        self.approval_status = "PENDING"
        self._approval_id = uuid.uuid4().hex[:8]

        categoria = content.get("categoria", "General")
        titulo = content.get("titulo_articulo", "Sin titulo")

        # Mensaje 1: Resumen con botones de aprobacion
        msg = f"📰 NUEVO CONTENIDO LISTO\n\n"
        msg += f"📂 Categoria: {categoria}\n"
        msg += f"📝 Titulo: {titulo}\n\n"
        msg += f"🐦 Hilo X (Previa):\n{content.get('hilo_x', '')[:500]}\n\n"
        msg += f"📘 Post FB (Previa):\n{content.get('post_facebook', '')[:500]}\n"

        keyboard = [
            [InlineKeyboardButton(
                "✅ Aprobar y Publicar",
                callback_data=f"approve_{self._approval_id}"
            )],
            [InlineKeyboardButton(
                "❌ Rechazar",
                callback_data=f"reject_{self._approval_id}"
            )],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await self._send_long_message(msg, reply_markup=reply_markup)

        # Mensaje 2: Articulo completo (puede ser largo, se divide automaticamente)
        articulo_msg = f"📄 ARTICULO WEB COMPLETO:\n\n"
        articulo_msg += f"{titulo}\n\n"
        articulo_msg += content.get("articulo_web", "(sin contenido)")
        await self._send_long_message(articulo_msg)

        # Mensaje 3: Guion de TikTok
        tiktok_msg = f"🎬 GUION DE TIKTOK:\n\n"
        tiktok_msg += content.get("guion_tiktok", "(sin contenido)")
        await self._send_long_message(tiktok_msg)

        print("  Mensajes enviados a Telegram. Esperando aprobacion...")

    def publish_to_wordpress(self, content):
        """Publicar articulo en WordPress via REST API."""
        wp_url = os.getenv("WP_URL", "")
        if not wp_url or wp_url == "https://tusitio.com/xmlrpc.php":
            print("  [WordPress] No configurado. Articulo guardado solo localmente.")
            return
        # TODO: Implementar cuando el usuario tenga WordPress
        print("  [WordPress] Publicando...")

    def publish_to_x(self, content):
        """Publicar hilo en X (Twitter)."""
        if not os.getenv("X_API_KEY"):
            print("  [X/Twitter] No configurado. Saltando.")
            return
        # TODO: Implementar cuando el usuario tenga API keys
        print("  [X/Twitter] Publicando...")

    def publish_to_facebook(self, content):
        """Publicar post en Facebook."""
        if not os.getenv("FB_PAGE_ACCESS_TOKEN"):
            print("  [Facebook] No configurado. Saltando.")
            return
        # TODO: Implementar cuando el usuario tenga API keys
        print("  [Facebook] Publicando...")

    def distribute_all(self):
        """Ejecuta la distribucion a todas las plataformas configuradas."""
        if self.current_content:
            self.publish_to_wordpress(self.current_content)
            self.publish_to_x(self.current_content)
            self.publish_to_facebook(self.current_content)
            print("  Distribucion completada.")

    async def run_batch_approval_flow(self, contenidos, categoria, timeout_seconds=600):
        """
        Envia un mensaje resumen de todos los articulos generados para la categoria
        y proporciona un teclado interactivo con botones toggle [🟢]/[🔴] para
        aprobarlos o rechazarlos individualmente.
        """
        if not contenidos:
            return []

        # Estado local de aprobacion: todos arrancan en True (aprobados por defecto)
        self._batch_state = {i: True for i in range(len(contenidos))}
        self._batch_done = False
        self._batch_id = uuid.uuid4().hex[:8]

        # Mensaje Resumen
        msg = f"📰 <b>CATEGORIA COMPLETADA: {categoria}</b>\n\n"
        msg += f"Se redactaron {len(contenidos)} artículos. Selecciona cuáles quieres publicar:\n\n"
        
        for i, c in enumerate(contenidos):
            titulo = c.get("titulo_articulo", "Sin titulo")
            region = c.get("region", "General")
            msg += f"<b>{i+1}.</b> [{region}] {titulo}\n"
            
        def _build_keyboard():
            keyboard = []
            row = []
            for i in range(len(contenidos)):
                estado = "🟢" if self._batch_state[i] else "🔴"
                row.append(InlineKeyboardButton(f"{estado} {i+1}", callback_data=f"toggle_{self._batch_id}_{i}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
                
            keyboard.append([InlineKeyboardButton("✅ CONFIRMAR PUBLICACION", callback_data=f"confirm_{self._batch_id}")])
            return InlineKeyboardMarkup(keyboard)

        # Enviar mensaje con parse_mode HTML
        try:
            await self.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=msg,
                reply_markup=_build_keyboard(),
                parse_mode="HTML"
            )
            print("  Mensaje batch enviado a Telegram. Esperando seleccion...")
        except Exception as e:
            print(f"  Error enviando mensaje a Telegram: {e}")
            return []

        # Iniciar Application para escuchar
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        async def button_callback(update, context):
            query = update.callback_query
            data = query.data
            
            if self._batch_id not in data:
                await query.answer("Este botón ya expiró.", show_alert=True)
                return

            if data.startswith("toggle_"):
                # Extraer indice
                idx = int(data.split("_")[2])
                self._batch_state[idx] = not self._batch_state[idx]
                await query.answer()
                # Actualizar teclado
                await query.edit_message_reply_markup(reply_markup=_build_keyboard())
                
            elif data.startswith("confirm_"):
                aprobados_count = sum(1 for v in self._batch_state.values() if v)
                await query.answer("Publicando seleccionados...")
                
                final_msg = query.message.text + f"\n\n✅ <b>PUBLICANDO {aprobados_count} ARTÍCULOS</b>"
                await query.edit_message_text(text=final_msg, parse_mode="HTML")
                self._batch_done = True

        application.add_handler(CallbackQueryHandler(button_callback))

        await application.initialize()
        await application.start()
        await application.updater.start_polling()

        elapsed = 0
        poll_interval = 2
        while not self._batch_done and elapsed < timeout_seconds:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        if not self._batch_done:
            print(f"  Timeout de {timeout_seconds}s. Cancelando batch.")
            self._batch_state = {i: False for i in range(len(contenidos))} # Rechazar todos

        await application.updater.stop()
        await application.stop()
        await application.shutdown()

        # Filtrar contenidos aprobados
        approved = [contenidos[i] for i in range(len(contenidos)) if self._batch_state[i]]
        return approved


async def start_telegram_listener(distributor, timeout_seconds=300):
    """
    Inicia un bot temporal para escuchar la respuesta de los botones.
    Incluye timeout para no esperar indefinidamente.
    """
    expected_id = distributor._approval_id
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    async def button_callback(update, context):
        query = update.callback_query
        await query.answer()

        # Verificar que el callback corresponde al contenido actual
        callback_data = query.data
        if not callback_data.endswith(expected_id):
            await query.answer("Este boton ya no es valido.", show_alert=True)
            return

        if callback_data.startswith("approve_"):
            new_text = query.message.text + "\n\n✅ Contenido APROBADO. Publicando..."
            # Truncar si el texto editado excede el limite
            if len(new_text) > TELEGRAM_MAX_LENGTH:
                new_text = new_text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n... (truncado)"
            await query.edit_message_text(text=new_text)
            distributor.approval_status = "APPROVED"
        elif callback_data.startswith("reject_"):
            new_text = query.message.text + "\n\n❌ Contenido RECHAZADO."
            if len(new_text) > TELEGRAM_MAX_LENGTH:
                new_text = new_text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n... (truncado)"
            await query.edit_message_text(text=new_text)
            distributor.approval_status = "REJECTED"

    application.add_handler(CallbackQueryHandler(button_callback))

    # Iniciar bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Esperar hasta que se tome una decision o se agote el timeout
    elapsed = 0
    poll_interval = 2
    while distributor.approval_status == "PENDING" and elapsed < timeout_seconds:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    if distributor.approval_status == "PENDING":
        print(f"  Timeout de {timeout_seconds}s alcanzado. Rechazando automaticamente.")
        distributor.approval_status = "REJECTED"

    # Detener bot
    await application.updater.stop()
    await application.stop()
    await application.shutdown()

    return distributor.approval_status
