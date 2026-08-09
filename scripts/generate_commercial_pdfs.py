from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output" / "pdf"
SCREENSHOT = ROOT / "outputs" / "turnoflow-admin-mobile-redesign.png"

PURPLE = HexColor("#7137FF")
PURPLE_DARK = HexColor("#3B296C")
LAVENDER = HexColor("#EEE7FF")
INK = HexColor("#111827")
MUTED = HexColor("#66748F")
LINE = HexColor("#D9DFEA")
BACKGROUND = HexColor("#F5F7FC")
NAVY = HexColor("#07111F")
MINT = HexColor("#D9F7EF")
GREEN = HexColor("#009879")
PINK = HexColor("#FFE3E8")
RED = HexColor("#EF476F")
YELLOW = HexColor("#FFF2C7")


def register_fonts() -> None:
    regular = Path("C:/Windows/Fonts/arial.ttf")
    bold = Path("C:/Windows/Fonts/arialbd.ttf")
    if regular.exists() and bold.exists():
        pdfmetrics.registerFont(TTFont("TF-Regular", str(regular)))
        pdfmetrics.registerFont(TTFont("TF-Bold", str(bold)))
    else:
        pdfmetrics.registerFont(TTFont("TF-Regular", "DejaVuSans.ttf"))
        pdfmetrics.registerFont(TTFont("TF-Bold", "DejaVuSans-Bold.ttf"))


def lines_for(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    size: float,
    color=INK,
    font: str = "TF-Regular",
    leading: float | None = None,
    max_lines: int | None = None,
) -> float:
    leading = leading or size * 1.28
    lines = lines_for(text, font, size, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def pill(pdf: canvas.Canvas, x: float, y: float, width: float, text: str, fill, color) -> None:
    pdf.setFillColor(fill)
    pdf.roundRect(x, y, width, 31, 15, stroke=0, fill=1)
    pdf.setFillColor(color)
    pdf.setFont("TF-Bold", 10)
    pdf.drawCentredString(x + width / 2, y + 10, text)


def card(pdf: canvas.Canvas, x: float, y: float, width: float, height: float, fill=white) -> None:
    pdf.setFillColor(fill)
    pdf.setStrokeColor(LINE)
    pdf.setLineWidth(1)
    pdf.roundRect(x, y, width, height, 15, stroke=1, fill=1)


def bullet(pdf: canvas.Canvas, x: float, y: float, text: str, width: float, color=GREEN) -> float:
    pdf.setFillColor(color)
    pdf.circle(x + 4, y + 4, 4, stroke=0, fill=1)
    return draw_text(pdf, text, x + 20, y, width - 20, 12, INK, leading=16)


def presentation_header(pdf: canvas.Canvas, section: str, page: int, dark: bool = False) -> None:
    foreground = white if dark else INK
    secondary = HexColor("#AAB5C6") if dark else MUTED
    pdf.setFillColor(foreground)
    pdf.setFont("TF-Bold", 16)
    pdf.drawString(42, 505, "TurnoFlow")
    pdf.setFillColor(secondary)
    pdf.setFont("TF-Bold", 8)
    pdf.drawString(42, 23, section.upper())
    pdf.drawRightString(918, 23, f"{page:02d}")


def generate_presentation(path: Path) -> None:
    width, height = 960, 540
    pdf = canvas.Canvas(str(path), pagesize=(width, height))
    pdf.setTitle("TurnoFlow - Presentación comercial")
    pdf.setAuthor("TurnoFlow")

    # 1. Portada
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "Sistema de gestión de turnos", 1)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 455, "PARA NEGOCIOS QUE TRABAJAN CON TURNOS")
    y = draw_text(pdf, "Más orden. Menos mensajes. Más turnos bajo control.", 60, 410, 585, 35, INK, "TF-Bold", 41)
    draw_text(
        pdf,
        "TurnoFlow reúne agenda, clientes, servicios, profesionales, cobros y disponibilidad en un panel simple.",
        60,
        y - 18,
        575,
        15,
        MUTED,
        leading=21,
    )
    pill(pdf, 60, 105, 130, "PANEL WEB", MINT, GREEN)
    pill(pdf, 204, 105, 160, "BOT CONFIGURABLE", LAVENDER, PURPLE_DARK)
    pill(pdf, 378, 105, 170, "15 DÍAS DE PRUEBA", PINK, RED)
    if SCREENSHOT.exists():
        pdf.setFillColor(white)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(700, 67, 180, 400, 28, stroke=1, fill=1)
        pdf.drawImage(str(SCREENSHOT), 713, 81, width=154, height=372, preserveAspectRatio=True, anchor="c", mask="auto")
    pdf.showPage()

    # 2. Problema
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "El costo oculto", 2)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "EL PROBLEMA")
    draw_text(pdf, "Agendar a mano parece gratis. Hasta que empieza a desordenar el día.", 60, 425, 830, 30, INK, "TF-Bold", 35)
    problems = [
        ("01", "Respuesta tardía", "La persona consulta, espera y puede elegir otro lugar."),
        ("02", "Agenda dispersa", "Chats, papel y memoria no muestran la misma disponibilidad."),
        ("03", "Errores y huecos", "Una superposición o cancelación afecta tiempo e ingresos."),
        ("04", "Caja poco clara", "Cuesta saber qué se cobró, canceló y qué sigue pendiente."),
    ]
    for index, (number, title, body) in enumerate(problems):
        x = 60 + (index % 2) * 440
        y0 = 220 - (index // 2) * 125
        card(pdf, x, y0, 400, 95)
        pdf.setFillColor(PURPLE)
        pdf.setFont("TF-Bold", 17)
        pdf.drawString(x + 20, y0 + 56, number)
        pdf.setFillColor(INK)
        pdf.setFont("TF-Bold", 13)
        pdf.drawString(x + 72, y0 + 58, title)
        draw_text(pdf, body, x + 72, y0 + 32, 300, 10, MUTED, leading=13)
    pdf.showPage()

    # 3. Solución
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "Una sola agenda", 3)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "LA SOLUCIÓN")
    draw_text(pdf, "Dos entradas. Una sola agenda.", 60, 425, 800, 32, INK, "TF-Bold")
    draw_text(pdf, "El negocio opera desde el panel y cada reserva actualiza la misma disponibilidad.", 60, 382, 820, 14, MUTED)
    card(pdf, 70, 120, 330, 205)
    pill(pdf, 94, 276, 145, "PANEL DE GESTIÓN", MINT, GREEN)
    draw_text(pdf, "Para quien administra", 94, 234, 270, 18, INK, "TF-Bold")
    draw_text(pdf, "Crear, confirmar, cobrar, mover, completar o cancelar turnos. Gestionar clientes, servicios, equipo y horarios.", 94, 196, 270, 12, MUTED, leading=17)
    card(pdf, 560, 120, 330, 205)
    pill(pdf, 584, 276, 185, "RESERVAS POR WHATSAPP", LAVENDER, PURPLE_DARK)
    draw_text(pdf, "Próxima integración", 584, 234, 270, 18, INK, "TF-Bold")
    draw_text(pdf, "El bot ya tiene el flujo preparado. La conexión real se hará únicamente mediante la API oficial de Meta.", 584, 196, 270, 12, MUTED, leading=17)
    pdf.setStrokeColor(PURPLE)
    pdf.setLineWidth(3)
    pdf.line(400, 222, 560, 222)
    pdf.setFillColor(PURPLE)
    pdf.circle(480, 222, 38, stroke=0, fill=1)
    pdf.setFillColor(white)
    pdf.setFont("TF-Bold", 10)
    pdf.drawCentredString(480, 226, "MISMA")
    pdf.drawCentredString(480, 212, "AGENDA")
    pdf.showPage()

    # 4. Flujo
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "Cómo funciona", 4)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "CÓMO FUNCIONA")
    draw_text(pdf, "Del pedido al turno confirmado, sin improvisar.", 60, 425, 820, 31, INK, "TF-Bold")
    steps = [
        ("1", "Consulta", "Servicio, precio, día y horario."),
        ("2", "Disponibilidad", "Revisa duración, reservas y bloqueos."),
        ("3", "Confirmación", "Valida otra vez antes de guardar."),
        ("4", "Gestión", "Aparece en agenda, historial y caja."),
    ]
    for index, (number, title, body) in enumerate(steps):
        x = 60 + index * 220
        pdf.setFillColor(GREEN if index == 3 else PURPLE)
        pdf.circle(x + 22, 310, 22, stroke=0, fill=1)
        pdf.setFillColor(white)
        pdf.setFont("TF-Bold", 13)
        pdf.drawCentredString(x + 22, 305, number)
        draw_text(pdf, title, x, 270, 190, 16, INK, "TF-Bold")
        draw_text(pdf, body, x, 235, 175, 11, MUTED, leading=15)
        if index < 3:
            pdf.setStrokeColor(LINE)
            pdf.setLineWidth(2)
            pdf.line(x + 46, 310, x + 210, 310)
    pdf.setFillColor(YELLOW)
    pdf.setStrokeColor(HexColor("#F1CA55"))
    pdf.roundRect(70, 75, 820, 62, 14, stroke=1, fill=1)
    pdf.setFillColor(HexColor("#8B6900"))
    pdf.setFont("TF-Bold", 9)
    pdf.drawString(92, 113, "DIFERENCIAL")
    draw_text(pdf, "La disponibilidad real manda: TurnoFlow no ofrece un horario ocupado ni superpone reservas.", 92, 92, 750, 12, INK, "TF-Bold")
    pdf.showPage()

    # 5. Producto
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "Panel de control", 5)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "LO QUE YA RESUELVE")
    draw_text(pdf, "Simple para aprender. Completo para operar.", 60, 420, 585, 31, INK, "TF-Bold", 36)
    features = [
        "Agenda de hoy, mañana, próximos e historial",
        "Cliente nuevo desde el mismo turno",
        "Servicios con precio y duración editable",
        "Profesionales, habilidades, horarios y bloqueos",
        "Cobros, extras, insumos y rendimiento",
        "Acceso privado y separado para cada negocio",
    ]
    fy = 310
    for feature in features:
        fy = bullet(pdf, 66, fy, feature, 520) - 16
    if SCREENSHOT.exists():
        pdf.setFillColor(white)
        pdf.setStrokeColor(LINE)
        pdf.roundRect(700, 67, 180, 400, 28, stroke=1, fill=1)
        pdf.drawImage(str(SCREENSHOT), 713, 81, width=154, height=372, preserveAspectRatio=True, anchor="c", mask="auto")
    pdf.showPage()

    # 6. Resultado
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "El resultado", 6)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "EL RESULTADO")
    draw_text(pdf, "TurnoFlow no agrega trabajo. Ordena el que ya existe.", 60, 425, 840, 30, INK, "TF-Bold")
    outcomes = [
        ("TIEMPO", "Menos ida y vuelta", "La información repetida queda disponible y la agenda se consulta en un solo lugar.", MINT, GREEN),
        ("CONTROL", "Menos errores", "Duración, profesional, reservas y bloqueos se validan antes de confirmar.", LAVENDER, PURPLE_DARK),
        ("DINERO", "Más claridad", "Turnos cobrados, cancelados, extras y potencial activo quedan visibles.", PINK, RED),
    ]
    for index, (label, title, body, fill, color) in enumerate(outcomes):
        x = 60 + index * 290
        card(pdf, x, 115, 260, 220)
        pill(pdf, x + 22, 280, 105, label, fill, color)
        draw_text(pdf, title, x + 22, 237, 216, 18, INK, "TF-Bold")
        draw_text(pdf, body, x + 22, 193, 216, 11, MUTED, leading=16)
    pdf.showPage()

    # 7. Piloto
    pdf.setFillColor(NAVY)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    presentation_header(pdf, "Programa piloto", 7, dark=True)
    pdf.setFillColor(HexColor("#B291FF"))
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(60, 463, "PROGRAMA PILOTO")
    draw_text(pdf, "15 días para comprobar si realmente ordena tu negocio.", 60, 418, 610, 34, white, "TF-Bold", 40)
    draw_text(pdf, "Configuramos servicios, precios, equipo, horarios y acceso. Durante la prueba acompañamos el uso y ajustamos la operación.", 60, 320, 590, 14, HexColor("#C8D1DF"), leading=20)
    items = ["Configuración personalizada", "Panel listo para celular", "Acompañamiento inicial", "Sin permanencia obligatoria"]
    for index, item in enumerate(items):
        x = 60 + (index % 2) * 300
        y0 = 230 - (index // 2) * 50
        pdf.setFillColor(GREEN)
        pdf.circle(x + 5, y0 + 4, 5, stroke=0, fill=1)
        pdf.setFillColor(white)
        pdf.setFont("TF-Bold", 11)
        pdf.drawString(x + 20, y0, item)
    pdf.setFillColor(white)
    pdf.roundRect(690, 120, 220, 245, 20, stroke=0, fill=1)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 9)
    pdf.drawString(722, 320, "PRÓXIMO PASO")
    draw_text(pdf, "Pedí una demo guiada", 722, 280, 158, 23, INK, "TF-Bold", 27)
    draw_text(pdf, "Respondé este mensaje y coordinamos una demostración.", 722, 205, 158, 11, MUTED, leading=16)
    pdf.setFillColor(PURPLE)
    pdf.roundRect(722, 145, 158, 38, 8, stroke=0, fill=1)
    pdf.setFillColor(white)
    pdf.setFont("TF-Bold", 11)
    pdf.drawCentredString(801, 158, "SOLICITAR DEMO")
    pdf.showPage()
    pdf.save()


def proposal_footer(pdf: canvas.Canvas, page: int) -> None:
    pdf.setStrokeColor(LINE)
    pdf.line(56, 805, 539, 805)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 18)
    pdf.drawString(56, 820, "TurnoFlow")
    pdf.setFillColor(MUTED)
    pdf.setFont("TF-Bold", 8)
    pdf.drawString(56, 32, "PROPUESTA COMERCIAL")
    pdf.drawRightString(539, 32, f"{page:02d}")


def generate_proposal(path: Path) -> None:
    width, height = A4
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.setTitle("TurnoFlow - Propuesta económica")
    pdf.setAuthor("TurnoFlow")

    # 1. Inversión
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    proposal_footer(pdf, 1)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(56, 760, "PROPUESTA DE IMPLEMENTACIÓN")
    draw_text(pdf, "TurnoFlow para tu negocio", 56, 715, 480, 27, INK, "TF-Bold")
    draw_text(pdf, "Sistema de gestión de turnos con configuración personalizada y acompañamiento inicial.", 56, 675, 455, 13, MUTED, leading=18)
    card(pdf, 56, 505, 225, 125)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 9)
    pdf.drawString(76, 600, "IMPLEMENTACIÓN")
    pdf.setFillColor(INK)
    pdf.setFont("TF-Bold", 28)
    pdf.drawString(76, 555, "USD 200")
    pdf.setFillColor(MUTED)
    pdf.setFont("TF-Regular", 10)
    pdf.drawString(76, 530, "pago único")
    pdf.setFillColor(NAVY)
    pdf.roundRect(314, 505, 225, 125, 14, stroke=0, fill=1)
    pdf.setFillColor(HexColor("#B291FF"))
    pdf.setFont("TF-Bold", 9)
    pdf.drawString(334, 600, "SERVICIO MENSUAL")
    pdf.setFillColor(white)
    pdf.setFont("TF-Bold", 28)
    pdf.drawString(334, 555, "USD 30")
    pdf.setFillColor(HexColor("#C8D1DF"))
    pdf.setFont("TF-Regular", 10)
    pdf.drawString(334, 530, "por mes")
    pdf.setFillColor(INK)
    pdf.setFont("TF-Bold", 17)
    pdf.drawString(56, 465, "La implementación incluye")
    included = [
        "Alta del negocio y acceso privado.",
        "Carga inicial de servicios, precios y duración.",
        "Configuración de profesionales, habilidades, días y horarios.",
        "Configuración del saludo y menú del bot.",
        "Capacitación y acompañamiento durante 15 días.",
        "Puesta en producción del panel de gestión.",
    ]
    iy = 425
    for item in included:
        iy = bullet(pdf, 60, iy, item, 460) - 8
    pdf.setFillColor(YELLOW)
    pdf.setStrokeColor(HexColor("#F1CA55"))
    pdf.roundRect(56, 90, 483, 80, 12, stroke=1, fill=1)
    pdf.setFillColor(HexColor("#8B6900"))
    pdf.setFont("TF-Bold", 8)
    pdf.drawString(76, 142, "FORMA DE PAGO")
    draw_text(pdf, "USD o equivalente en moneda local al tipo de cambio acordado el día del pago.", 76, 118, 440, 11, INK, "TF-Bold")
    pdf.showPage()

    # 2. Alcance
    pdf.setFillColor(BACKGROUND)
    pdf.rect(0, 0, width, height, stroke=0, fill=1)
    proposal_footer(pdf, 2)
    pdf.setFillColor(PURPLE)
    pdf.setFont("TF-Bold", 10)
    pdf.drawString(56, 760, "ALCANCE Y CONDICIONES")
    draw_text(pdf, "Qué mantiene activo el servicio mensual", 56, 715, 485, 25, INK, "TF-Bold")
    monthly = [
        "Hosting y base de datos dentro del uso inicial acordado.",
        "Mantenimiento técnico y corrección de errores.",
        "Actualizaciones de seguridad y compatibilidad.",
        "Soporte remoto para dudas operativas razonables.",
        "Monitoreo básico del funcionamiento.",
    ]
    my = 655
    for item in monthly:
        my = bullet(pdf, 60, my, item, 470) - 8
    card(pdf, 56, 385, 483, 118)
    pdf.setFillColor(RED)
    pdf.setFont("TF-Bold", 9)
    pdf.drawString(76, 472, "NO INCLUIDO")
    draw_text(
        pdf,
        "Integración y cargos de WhatsApp Business Platform de Meta; campañas masivas; desarrollos especiales; pagos en línea; facturación; dominio propio o infraestructura adicional por crecimiento extraordinario.",
        76,
        440,
        440,
        11,
        MUTED,
        leading=16,
    )
    pdf.setFillColor(INK)
    pdf.setFont("TF-Bold", 17)
    pdf.drawString(56, 350, "Cómo empezamos")
    steps = [
        ("1", "Relevamiento", "Servicios, equipo y horarios."),
        ("2", "Configuración", "Dejamos el panel listo."),
        ("3", "Prueba", "15 días de uso acompañado."),
    ]
    for index, (number, title, body) in enumerate(steps):
        x = 56 + index * 164
        card(pdf, x, 195, 145, 125)
        pdf.setFillColor(PURPLE)
        pdf.circle(x + 25, 285, 15, stroke=0, fill=1)
        pdf.setFillColor(white)
        pdf.setFont("TF-Bold", 10)
        pdf.drawCentredString(x + 25, 281, number)
        draw_text(pdf, title, x + 48, 288, 85, 10, INK, "TF-Bold")
        draw_text(pdf, body, x + 18, 245, 108, 9, MUTED, leading=12)
    pdf.setFillColor(NAVY)
    pdf.roundRect(56, 78, 483, 90, 12, stroke=0, fill=1)
    pdf.setFillColor(HexColor("#B291FF"))
    pdf.setFont("TF-Bold", 8)
    pdf.drawString(78, 140, "SIGUIENTE PASO")
    draw_text(pdf, "Confirmar la propuesta y coordinar la configuración inicial.", 78, 112, 420, 13, white, "TF-Bold")
    pdf.setFillColor(MUTED)
    pdf.setFont("TF-Regular", 8)
    pdf.drawString(56, 54, "Vigencia sugerida: 15 días. La conexión con WhatsApp se cotiza al momento de activarla.")
    pdf.showPage()
    pdf.save()


def main() -> None:
    register_fonts()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generate_presentation(OUTPUT_DIR / "TurnoFlow_presentacion_comercial_2026.pdf")
    generate_proposal(OUTPUT_DIR / "TurnoFlow_propuesta_economica_2026.pdf")
    print("PDF comerciales generados correctamente.")


if __name__ == "__main__":
    main()
