"""Trabalhos: escrever no robô (laser/caneta), diagnóstico e exportação 3D."""

import math
import time

from .protocol import PTP_MOVJ_XYZ, Aborted, DobotError

# Distância da ponta da ferramenta ao eixo do 4.º motor (mm), usada pelo
# firmware para calcular X/Y/Z. Confirme no DobotStudio (End Tool).
TOOL_OFFSETS = {"laser": 70.0, "caneta": 61.0}


def write_on_robot(dobot, robot_strokes, z, tool="laser", draw_speed=15.0,
                   travel_speed=80.0, lift=None, dwell_ms=150,
                   set_tool_offset=True, progress=None, log=print):
    """Escreve os traços (coordenadas do robô, mm) à altura `z`.

    laser : o laser liga em cada traço e desliga entre traços.
    caneta: a ferramenta sobe `lift` mm entre traços (bom para testar a
            programação com uma caneta antes de usar o laser).
    """
    if tool not in TOOL_OFFSETS:
        raise ValueError(f"Ferramenta desconhecida: {tool}")
    if lift is None:
        lift = 0.0 if tool == "laser" else 10.0
    laser = tool == "laser"
    safe_z = z + max(lift, 10.0)
    draw_ratio = max(1.0, min(100.0, 100.0 * draw_speed / travel_speed))

    dobot.abort_event.clear()
    alarms = dobot.get_alarms()
    if alarms:
        log(f"Alarmes ativos {alarms}: a limpar.")
        dobot.clear_alarms()
    dobot.reset_queue()
    if set_tool_offset:
        dobot.set_end_effector_offset(TOOL_OFFSETS[tool])
    dobot.set_speed(travel_speed, travel_speed * 2)

    try:
        if laser:
            dobot.laser(False)
        dobot.queue_speed_ratio(100)
        x0, y0 = robot_strokes[0][0]
        dobot.move(x0, y0, safe_z, mode=PTP_MOVJ_XYZ)
        total = len(robot_strokes)
        for n, stroke in enumerate(robot_strokes, 1):
            (sx, sy), rest = stroke[0], stroke[1:] or [stroke[0]]
            dobot.queue_speed_ratio(100)
            dobot.move(sx, sy, z + lift)
            if lift:
                dobot.move(sx, sy, z)
            dobot.queue_speed_ratio(draw_ratio)
            if laser:
                dobot.laser(True)
                dobot.wait_ms(dwell_ms)
            for x, y in rest:
                dobot.move(x, y, z)
            if laser:
                dobot.laser(False)
            if lift:
                dobot.queue_speed_ratio(100)
                dobot.move(rest[-1][0], rest[-1][1], z + lift)
            if progress:
                progress(n, total)
        dobot.queue_speed_ratio(100)
        x1, y1 = robot_strokes[-1][-1]
        dobot.move(x1, y1, safe_z)
        dobot.wait_until_done()
    except Aborted:
        stop(dobot)
        raise
    log("Concluído.")


def stop(dobot):
    """Paragem imediata: para a fila e desliga o laser."""
    dobot.abort_event.set()
    try:
        dobot.queue_force_stop()
        dobot.queue_clear()
        dobot.laser(False, queued=False)
    except DobotError:
        pass


def diagnose(dobot, test_move=True, test_laser=False, log=print):
    """Verifica, passo a passo, porque é que o robô não executa programas."""
    ok = True
    try:
        log(f"Ligado a: {dobot.device_name() or 'Dobot'}")
    except DobotError as exc:
        log(f"ERRO: {exc}")
        return False

    x, y, z, r = dobot.get_pose()
    log(f"Posição atual: X={x:.1f} Y={y:.1f} Z={z:.1f} R={r:.1f}")

    alarms = dobot.get_alarms()
    if alarms:
        ok = False
        log(f"ALARMES ATIVOS: {alarms}. Enquanto houver alarmes (LED vermelho) "
            "o robô ignora programas. A limpar alarmes...")
        dobot.clear_alarms()
        alarms = dobot.get_alarms()
        log("Alarmes limpos." if not alarms else
            f"Os alarmes continuam {alarms}: faça Home e verifique os limites.")
    else:
        log("Sem alarmes.")

    log("A reiniciar a fila de comandos (Stop -> Clear -> Start)...")
    dobot.reset_queue()

    if test_move:
        log("Teste da fila: subir 10 mm e voltar.")
        dobot.set_speed(50, 100)
        dobot.move(x, y, z + 10)
        dobot.move(x, y, z)
        try:
            dobot.wait_until_done(timeout=15)
            log("OK: o robô executa comandos programados.")
        except DobotError:
            ok = False
            log("FALHOU: o robô aceitou os comandos mas não os executou. "
                "Faça Home, confirme que o LED está verde e atualize o "
                "firmware no DobotStudio.")

    if test_laser:
        log("Teste do laser: 1 segundo ligado (use os óculos de proteção!).")
        dobot.laser(True, queued=False)
        time.sleep(1.0)
        dobot.laser(False, queued=False)
        log("Se o laser não acendeu: cabo de alimentação na porta SW4, cabo "
            "de sinal na porta GP5, e firmware no modo normal (não 3D).")
    return ok


# --- impressão 3D ----------------------------------------------------------

def _prism(poly, z0, z1):
    """Triângulos de um prisma vertical de base convexa `poly`."""
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))
    if area < 0:
        poly = poly[::-1]
    tris = []
    for i in range(1, len(poly) - 1):
        a, b, c = poly[0], poly[i], poly[i + 1]
        tris.append(((*a, z1), (*b, z1), (*c, z1)))
        tris.append(((*a, z0), (*c, z0), (*b, z0)))
    for a, b in zip(poly, poly[1:] + poly[:1]):
        tris.append(((*a, z0), (*b, z0), (*b, z1)))
        tris.append(((*a, z0), (*b, z1), (*a, z1)))
    return tris


def _disc(cx, cy, radius, sides=12):
    return [(cx + radius * math.cos(2 * math.pi * k / sides),
             cy + radius * math.sin(2 * math.pi * k / sides)) for k in range(sides)]


def strokes_to_triangles(strokes, line_width=1.2, height=3.0, base=1.0, margin=3.0):
    """Letras em relevo (traços com largura `line_width`) sobre uma placa
    de espessura `base` (0 = sem placa). Coordenadas de papel em mm."""
    half = line_width / 2
    z0, z1 = base, base + height
    tris = []
    for s in strokes:
        for x, y in s:
            tris += _prism(_disc(x, y, half), z0 - 0.01 if base else 0, z1)
        for (ax, ay), (bx, by) in zip(s, s[1:]):
            length = math.hypot(bx - ax, by - ay)
            if length < 1e-6:
                continue
            nx, ny = -(by - ay) / length * half, (bx - ax) / length * half
            quad = [(ax + nx, ay + ny), (bx + nx, by + ny),
                    (bx - nx, by - ny), (ax - nx, ay - ny)]
            tris += _prism(quad, z0 - 0.01 if base else 0, z1)
    if base:
        xs = [x for s in strokes for x, _ in s]
        ys = [y for s in strokes for _, y in s]
        m = margin + half
        plate = [(min(xs) - m, min(ys) - m), (max(xs) + m, min(ys) - m),
                 (max(xs) + m, max(ys) + m), (min(xs) - m, max(ys) + m)]
        tris += _prism(plate, 0.0, base)
    return tris


def to_stl(triangles, name="texto"):
    out = [f"solid {name}"]
    for a, b, c in triangles:
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
             u[0] * v[1] - u[1] * v[0])
        size = math.sqrt(sum(k * k for k in n)) or 1.0
        out.append(f"facet normal {n[0]/size:.6f} {n[1]/size:.6f} {n[2]/size:.6f}")
        out.append("outer loop")
        for p in (a, b, c):
            out.append(f"vertex {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
        out.append("endloop")
        out.append("endfacet")
    out.append(f"endsolid {name}")
    return "\n".join(out) + "\n"


def strokes_to_gcode(strokes, center_x=0.0, center_y=0.0, layers=8,
                     layer_height=0.2, first_z=0.2, line_width=0.6,
                     filament_mm=1.75, temperature=200, print_speed=10.0,
                     travel_speed=30.0, retract=1.0, home=True):
    """G-code (Marlin) que traça as letras camada a camada.

    Só funciona com o firmware de impressão 3D do Dobot instalado. As
    coordenadas (center_x, center_y) são as do referencial da impressora
    mostrado no Repetier-Host: confirme-as antes de imprimir.
    """
    layers = max(1, int(layers))
    filament_area = math.pi * (filament_mm / 2) ** 2
    e_per_mm = layer_height * line_width / filament_area
    f_print, f_travel = print_speed * 60, travel_speed * 60
    g = [
        "; Texto gerado por dobot_writer",
        "G21 ; mm", "G90 ; absoluto", "M82 ; extrusao absoluta",
        f"M104 S{temperature}", f"M109 S{temperature} ; aquecer bico",
    ]
    if home:
        g.append("G28")
    g += ["G92 E0", f"G1 Z{first_z + 5:.2f} F{f_travel:.0f}"]
    e = 0.0
    for layer in range(layers):
        z = first_z + layer * layer_height
        order = strokes if layer % 2 == 0 else [s[::-1] for s in reversed(strokes)]
        for s in order:
            if len(s) < 2:
                continue
            sx, sy = s[0]
            e -= retract
            g.append(f"G1 E{e:.4f} F1800")
            g.append(f"G0 Z{z + 1:.2f} F{f_travel:.0f}")
            g.append(f"G0 X{center_x + sx:.2f} Y{center_y + sy:.2f} F{f_travel:.0f}")
            g.append(f"G0 Z{z:.2f}")
            e += retract
            g.append(f"G1 E{e:.4f} F1800")
            for (ax, ay), (bx, by) in zip(s, s[1:]):
                e += math.hypot(bx - ax, by - ay) * e_per_mm
                g.append(f"G1 X{center_x + bx:.2f} Y{center_y + by:.2f} "
                         f"E{e:.4f} F{f_print:.0f}")
    g += [f"G1 E{e - retract:.4f} F1800", f"G0 Z{z + 10:.2f}",
          "M104 S0 ; desligar bico", "M84", ""]
    return "\n".join(g)
